from __future__ import annotations

import asyncio
import json
import os
import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime

import httpx
from azure.identity import AzureCliCredential, DefaultAzureCredential

from sp500_candidate_engine.analytics.azure_openai import AzureOpenAIClient
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid
from sp500_candidate_engine.llm_preselection.config import LlmPreselectionConfig
from sp500_candidate_engine.llm_preselection.evidence import EvidencePacket
from sp500_candidate_engine.llm_preselection.rate_limits import LlmRateLimiter

_REASON_CODES = (
    "BUSINESS_MOMENTUM",
    "FUNDAMENTAL_STRENGTH",
    "MATERIAL_EVENT",
    "MARKET_CONFIRMATION",
    "EVIDENCE_LIMITED",
    "NEGATIVE_EVENT",
    "WEAK_FUNDAMENTALS",
    "MARKET_DIVERGENCE",
)
_QUALITY_LEVELS = ("HIGH", "MEDIUM", "LOW")
_UNCERTAINTY_LEVELS = ("LOW", "MEDIUM", "HIGH")


@dataclass(frozen=True)
class LlmRankerSettings:
    endpoint: str
    deployment: str
    api_version: str
    timeout_seconds: float = 60.0
    credential_mode: str = "default"
    tenant_id: str | None = None

    @classmethod
    def from_env(cls) -> LlmRankerSettings:
        def required(name: str) -> str:
            value = os.getenv(name, "").strip()
            if not value:
                raise ValueError(f"Required environment variable is missing: {name}")
            return value

        enabled = os.getenv("LLM_PRESELECTION_ENABLED", "false").strip().lower()
        if enabled not in {"true", "1", "yes"}:
            raise ValueError("LLM_PRESELECTION_ENABLED must be true")
        settings = cls(
            endpoint=required("AZURE_OPENAI_ENDPOINT"),
            deployment=required("AZURE_OPENAI_DEPLOYMENT"),
            api_version=required("AZURE_OPENAI_API_VERSION"),
            timeout_seconds=float(os.getenv("AZURE_OPENAI_TIMEOUT_SECONDS", "60")),
            credential_mode=os.getenv("AZURE_CREDENTIAL_MODE", "default").strip(),
            tenant_id=os.getenv("AZURE_TENANT_ID", "").strip() or None,
        )
        if settings.credential_mode not in {"default", "azure_cli"}:
            raise ValueError("AZURE_CREDENTIAL_MODE must be default or azure_cli")
        return settings


@dataclass(frozen=True)
class CallAttempt:
    call_attempt_id: uuid.UUID
    stage: str
    batch_no: int
    attempt_no: int
    input_hash: str
    output_hash: str | None
    status: str
    http_status: int | None
    error_code: str | None
    input_tokens: int | None
    output_tokens: int | None
    total_tokens: int | None
    started_at: datetime
    finished_at: datetime
    response_output: dict[str, object] | None = None
    cache_source_attempt_id: uuid.UUID | None = None


@dataclass(frozen=True)
class CachedCompletion:
    output: dict[str, object]
    output_hash: str
    call_attempt_id: uuid.UUID


@dataclass(frozen=True)
class InstrumentAssessment:
    instrument_id: uuid.UUID
    batch_no: int
    first_stage_rank: int
    score: float | None
    sub_scores: dict[str, float | None]
    evidence_quality: str
    uncertainty: str
    reason_codes: tuple[str, ...]
    rationale: str
    evidence_ids: tuple[uuid.UUID, ...]
    output_hash: str
    criterion_evidence: tuple[dict[str, str], ...] = ()
    missing_reasons: dict[str, str] = field(default_factory=dict)
    weight_denominator: int | None = None
    supported_count: int | None = None


@dataclass(frozen=True)
class FinalCandidate:
    instrument_id: uuid.UUID
    position: int
    score: float
    reason_codes: tuple[str, ...]
    evidence_ids: tuple[uuid.UUID, ...]


@dataclass(frozen=True)
class RankingResult:
    assessments: tuple[InstrumentAssessment, ...]
    candidates: tuple[FinalCandidate, ...]
    attempts: tuple[CallAttempt, ...]


class LlmRankingError(RuntimeError):
    def __init__(self, message: str, attempts: tuple[CallAttempt, ...]) -> None:
        super().__init__(message)
        self.attempts = attempts


class AzureOpenAIPreselectionRanker:
    def __init__(
        self,
        settings: LlmRankerSettings,
        config: LlmPreselectionConfig,
        *,
        client: AzureOpenAIClient | None = None,
    ) -> None:
        self.settings = settings
        self.config = config
        if client is None:
            credential = (
                (
                    AzureCliCredential(tenant_id=settings.tenant_id)
                    if settings.tenant_id is not None else AzureCliCredential()
                )
                if settings.credential_mode == "azure_cli"
                else DefaultAzureCredential()
            )
            client = AzureOpenAIClient(
                endpoint=settings.endpoint,
                deployment=settings.deployment,
                api_version=settings.api_version,
                timeout_seconds=settings.timeout_seconds,
                credential=credential,
            )
        self.client = client
        self.response_cache: Callable[[str, uuid.UUID, bool], CachedCompletion | None] | None = None
        self.rate_limiter = LlmRateLimiter(config.rate_limits) if config.rate_limits else None

    async def aclose(self) -> None:
        await self.client.aclose()

    async def rank(
        self,
        *,
        llm_ranking_run_id: uuid.UUID,
        packets: tuple[EvidencePacket, ...],
    ) -> RankingResult:
        if len(packets) < self.config.requested_count:
            raise LlmRankingError("Insufficient eligible evidence packets", ())
        attempts: list[CallAttempt] = []
        assessments: list[InstrumentAssessment] = []
        ordered_packets = sorted(packets, key=lambda packet: packet.instrument_id.hex)
        try:
            for start in range(0, len(ordered_packets), self.config.batch_size):
                batch_no = start // self.config.batch_size
                batch = ordered_packets[start : start + self.config.batch_size]
                output, output_hash, call_attempts = await self._call(
                    run_id=llm_ranking_run_id,
                    stage="INSTRUMENT_BATCH",
                    batch_no=batch_no,
                    messages=self._assessment_messages(batch),
                    schema_name="instrument_assessments",
                    schema=self._assessment_schema(batch),
                )
                attempts.extend(call_attempts)
                try:
                    parsed_assessments = self._parse_assessments(
                        output=output,
                        output_hash=output_hash,
                        batch_no=batch_no,
                        packets=batch,
                    )
                except LlmRankingError:
                    raise
                except (KeyError, TypeError, ValueError) as error:
                    raise LlmRankingError(
                        "Instrument assessment output is malformed", ()
                    ) from error
                assessments.extend(parsed_assessments)
            assessments = sorted(
                assessments,
                key=lambda item: (
                    -_required_score(item), item.instrument_id.hex
                ),
            )
            assessments = [
                InstrumentAssessment(
                    **{
                        **item.__dict__,
                        "first_stage_rank": rank,
                    }
                )
                for rank, item in enumerate(assessments, start=1)
            ]
            pool = tuple(assessments[: self.config.first_stage_pool_size])
            packet_by_id = {packet.instrument_id: packet for packet in packets}
            output, _output_hash, call_attempts = await self._call(
                run_id=llm_ranking_run_id,
                stage="FINAL_RANK",
                batch_no=0,
                messages=self._final_messages(pool, packet_by_id),
                schema_name="final_preselection",
                schema=self._final_schema(pool),
            )
            attempts.extend(call_attempts)
            try:
                candidates = self._parse_final(output, pool, packet_by_id)
            except LlmRankingError:
                raise
            except (KeyError, TypeError, ValueError) as error:
                raise LlmRankingError(
                    "Final ranking output is malformed", ()
                ) from error
        except LlmRankingError as error:
            raise LlmRankingError(
                str(error), tuple([*attempts, *error.attempts])
            ) from error
        return RankingResult(
            assessments=tuple(assessments),
            candidates=candidates,
            attempts=tuple(attempts),
        )

    async def _call(
        self,
        *,
        run_id: uuid.UUID,
        stage: str,
        batch_no: int,
        messages: list[dict[str, str]],
        schema_name: str,
        schema: dict[str, object],
        execution_context_id: uuid.UUID | None = None,
        attempt_offset: int = 0,
    ) -> tuple[dict[str, object], str, tuple[CallAttempt, ...]]:
        input_hash = _canonical_hash(
            {"messages": messages, "schema_name": schema_name, "schema": schema}
        )
        if self.response_cache is not None:
            if execution_context_id is None:
                raise LlmRankingError("Cached evaluation requires an execution context", ())
            cached = await asyncio.to_thread(
                self.response_cache, input_hash, execution_context_id, attempt_offset == 0
            )
            if cached is not None:
                if _canonical_hash(cached.output) != cached.output_hash:
                    raise LlmRankingError("Cached response hash mismatch", ())
                now = datetime.now(UTC)
                attempt = CallAttempt(
                    _stable_uuid(
                        "llm-cache-attempt",
                        f"{run_id}:{stage}:{batch_no}:{attempt_offset + 1}:{input_hash}",
                    ),
                    stage, batch_no, attempt_offset + 1, input_hash,
                    cached.output_hash, "SUCCEEDED",
                    None, None, 0, 0, 0, now, now, cached.output, cached.call_attempt_id,
                )
                return cached.output, cached.output_hash, (attempt,)
        attempts: list[CallAttempt] = []
        for attempt_no in range(attempt_offset + 1, self.config.max_attempts + 1):
            started_at = datetime.now(UTC)
            attempt_id = _stable_uuid(
                "llm-call-attempt",
                f"{run_id}:{stage}:{batch_no}:{attempt_no}:{input_hash}",
            )
            try:
                if self.rate_limiter is not None:
                    estimated = (len(json.dumps(messages)) + len(json.dumps(schema)) + 3) // 4
                    await self.rate_limiter.acquire(estimated)
                response = await self.client.complete(
                    messages=messages,
                    schema_name=schema_name,
                    schema=schema,
                )
                if self.rate_limiter is not None:
                    self.rate_limiter.record_usage(response.total_tokens)
                output_hash = _canonical_hash(response.output)
                attempts.append(
                    CallAttempt(
                        call_attempt_id=attempt_id,
                        stage=stage,
                        batch_no=batch_no,
                        attempt_no=attempt_no,
                        input_hash=input_hash,
                        output_hash=output_hash,
                        status="SUCCEEDED",
                        http_status=200,
                        error_code=None,
                        input_tokens=response.input_tokens,
                        output_tokens=response.output_tokens,
                        total_tokens=response.total_tokens,
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                        response_output=response.output,
                    )
                )
                return response.output, output_hash, tuple(attempts)
            except Exception as error:
                status = (
                    error.response.status_code
                    if isinstance(error, httpx.HTTPStatusError)
                    else None
                )
                error_code = type(error).__name__
                attempts.append(
                    CallAttempt(
                        call_attempt_id=attempt_id,
                        stage=stage,
                        batch_no=batch_no,
                        attempt_no=attempt_no,
                        input_hash=input_hash,
                        output_hash=None,
                        status="FAILED",
                        http_status=status,
                        error_code=error_code,
                        input_tokens=None,
                        output_tokens=None,
                        total_tokens=None,
                        started_at=started_at,
                        finished_at=datetime.now(UTC),
                    )
                )
                retryable = status in {408, 429, 500, 502, 503, 504} or isinstance(
                    error, (httpx.TimeoutException, httpx.TransportError)
                )
                if not retryable or attempt_no == self.config.max_attempts:
                    raise LlmRankingError(
                        f"{stage} Azure OpenAI call failed: {error_code}",
                        tuple(attempts),
                    ) from error
                delay = self.config.base_delay_seconds * (2 ** (attempt_no - 1))
                if isinstance(error, httpx.HTTPStatusError):
                    retry_after = error.response.headers.get("Retry-After", "")
                    if retry_after.isdigit():
                        delay = max(delay, float(retry_after))
                if delay > self.config.max_delay_seconds:
                    raise LlmRankingError(
                        "Provider retry delay exceeds the configured budget", tuple(attempts)
                    ) from error
                await asyncio.sleep(delay)
        raise AssertionError("unreachable")

    def _assessment_messages(
        self, packets: list[EvidencePacket]
    ) -> list[dict[str, str]]:
        evidence = [
            {
                "instrument_id": str(packet.instrument_id),
                "evidence_ids": [
                    str(link.evidence_link_id) for link in packet.links
                ],
                "packet": packet.packet,
            }
            for packet in packets
        ]
        return [
            {
                "role": "system",
                "content": (
                    "Rank only from the supplied point-in-time evidence. Do not use "
                    "external knowledge or web search. This is an analysis-candidate "
                    "score, not investment advice. Score every supplied instrument "
                    f"once. Prompt version: {self.config.prompt_version}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(evidence, sort_keys=True, ensure_ascii=True),
            },
        ]

    def _assessment_schema(
        self, packets: list[EvidencePacket]
    ) -> dict[str, object]:
        instrument_ids = [str(packet.instrument_id) for packet in packets]
        evidence_ids = [
            str(link.evidence_link_id)
            for packet in packets
            for link in packet.links
        ]
        sub_score_properties = {
            key: {"type": "number", "minimum": 0, "maximum": 100}
            for key in self.config.rubric
        }
        item = {
            "type": "object",
            "properties": {
                "instrument_id": {"type": "string", "enum": instrument_ids},
                "score": {"type": "number", "minimum": 0, "maximum": 100},
                "sub_scores": {
                    "type": "object",
                    "properties": sub_score_properties,
                    "required": list(sub_score_properties),
                    "additionalProperties": False,
                },
                "evidence_quality": {"type": "string", "enum": list(_QUALITY_LEVELS)},
                "uncertainty": {"type": "string", "enum": list(_UNCERTAINTY_LEVELS)},
                "reason_codes": {
                    "type": "array",
                    "items": {"type": "string", "enum": list(_REASON_CODES)},
                    "uniqueItems": True,
                    "minItems": 1,
                    "maxItems": 10,
                },
                "rationale": {
                    "type": "string",
                    "maxLength": self.config.limits.rationale_characters,
                },
                "evidence_ids": {
                    "type": "array",
                    "items": {"type": "string", "enum": evidence_ids},
                    "uniqueItems": True,
                    "minItems": 1,
                    "maxItems": 10,
                },
            },
            "required": [
                "instrument_id",
                "score",
                "sub_scores",
                "evidence_quality",
                "uncertainty",
                "reason_codes",
                "rationale",
                "evidence_ids",
            ],
            "additionalProperties": False,
        }
        return {
            "type": "object",
            "properties": {
                "assessments": {
                    "type": "array",
                    "items": item,
                    "minItems": len(packets),
                    "maxItems": len(packets),
                }
            },
            "required": ["assessments"],
            "additionalProperties": False,
        }

    def _parse_assessments(
        self,
        *,
        output: dict[str, object],
        output_hash: str,
        batch_no: int,
        packets: list[EvidencePacket],
    ) -> list[InstrumentAssessment]:
        values = output.get("assessments")
        if not isinstance(values, list):
            raise LlmRankingError("Missing assessments output", ())
        packet_by_id = {packet.instrument_id: packet for packet in packets}
        result = []
        seen: set[uuid.UUID] = set()
        for value in values:
            if not isinstance(value, dict):
                raise LlmRankingError("Assessment must be an object", ())
            instrument_id = uuid.UUID(str(value["instrument_id"]))
            if instrument_id in seen or instrument_id not in packet_by_id:
                raise LlmRankingError("Assessment instrument set is invalid", ())
            seen.add(instrument_id)
            packet = packet_by_id[instrument_id]
            allowed_evidence = {link.evidence_link_id for link in packet.links}
            evidence_ids = tuple(uuid.UUID(str(item)) for item in value["evidence_ids"])
            if (
                not evidence_ids
                or len(evidence_ids) > 10
                or any(item not in allowed_evidence for item in evidence_ids)
            ):
                raise LlmRankingError("Assessment evidence reference is invalid", ())
            sub_scores: dict[str, float | None] = {
                str(key): float(score)
                for key, score in dict(value["sub_scores"]).items()
            }
            score = float(value["score"])
            evidence_quality = str(value["evidence_quality"])
            uncertainty = str(value["uncertainty"])
            reason_codes = tuple(str(item) for item in value["reason_codes"])
            rationale = str(value["rationale"])
            if (
                set(sub_scores) != set(self.config.rubric)
                or not 0 <= score <= 100
                or any(item is None or not 0 <= item <= 100 for item in sub_scores.values())
                or evidence_quality not in _QUALITY_LEVELS
                or uncertainty not in _UNCERTAINTY_LEVELS
                or not reason_codes
                or any(item not in _REASON_CODES for item in reason_codes)
                or len(set(reason_codes)) != len(reason_codes)
                or len(rationale) > self.config.limits.rationale_characters
            ):
                raise LlmRankingError("Assessment rubric is invalid", ())
            result.append(
                InstrumentAssessment(
                    instrument_id=instrument_id,
                    batch_no=batch_no,
                    first_stage_rank=0,
                    score=score,
                    sub_scores=sub_scores,
                    evidence_quality=evidence_quality,
                    uncertainty=uncertainty,
                    reason_codes=reason_codes,
                    rationale=rationale,
                    evidence_ids=evidence_ids,
                    output_hash=output_hash,
                )
            )
        if seen != set(packet_by_id):
            raise LlmRankingError("Not every instrument was assessed", ())
        return result

    def _final_messages(
        self,
        pool: tuple[InstrumentAssessment, ...],
        packet_by_id: dict[uuid.UUID, EvidencePacket],
    ) -> list[dict[str, str]]:
        values = [
            {
                "instrument_id": str(item.instrument_id),
                "first_stage_rank": item.first_stage_rank,
                "first_stage_score": item.score,
                "sub_scores": item.sub_scores,
                "evidence_quality": item.evidence_quality,
                "uncertainty": item.uncertainty,
                "reason_codes": list(item.reason_codes),
                "rationale": item.rationale,
                "evidence_ids": [
                    str(link.evidence_link_id)
                    for link in packet_by_id[item.instrument_id].links
                ],
                "packet_summary": self._packet_summary(
                    packet_by_id[item.instrument_id]
                ),
            }
            for item in pool
        ]
        return [
            {
                "role": "system",
                "content": (
                    "Select exactly 20 downstream analysis candidates using only the "
                    "supplied point-in-time evidence and first-stage assessments. Do "
                    "not give investment advice or use external knowledge. Return each "
                    f"instrument once. Prompt version: {self.config.prompt_version}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(values, sort_keys=True, ensure_ascii=True),
            },
        ]

    @staticmethod
    def _packet_summary(packet: EvidencePacket) -> dict[str, object]:
        def items(key: str, maximum: int) -> list[object]:
            value = packet.packet.get(key)
            return value[:maximum] if isinstance(value, list) else []

        identity = packet.packet.get("identity")
        price_context = packet.packet.get("price_context")
        return {
            "identity": identity if isinstance(identity, dict) else {},
            "price_context": (
                price_context if isinstance(price_context, dict) else {}
            ),
            "section_counts": packet.section_counts,
            "missing_sections": list(packet.missing_sections),
            "recent_news": items("news", 3),
            "recent_earnings": items("earnings", 2),
            "recent_filings": items("filings", 5),
        }

    def _final_schema(
        self, pool: tuple[InstrumentAssessment, ...]
    ) -> dict[str, object]:
        instrument_ids = [str(item.instrument_id) for item in pool]
        return {
            "type": "object",
            "properties": {
                "candidates": {
                    "type": "array",
                    "minItems": self.config.requested_count,
                    "maxItems": self.config.requested_count,
                    "items": {
                        "type": "object",
                        "properties": {
                            "instrument_id": {
                                "type": "string",
                                "enum": instrument_ids,
                            },
                            "position": {
                                "type": "integer",
                                "minimum": 1,
                                "maximum": self.config.requested_count,
                            },
                            "score": {
                                "type": "number",
                                "minimum": 0,
                                "maximum": 100,
                            },
                            "reason_codes": {
                                "type": "array",
                                "items": {
                                    "type": "string",
                                    "enum": list(_REASON_CODES),
                                },
                                "uniqueItems": True,
                                "minItems": 1,
                                "maxItems": 10,
                            },
                            "evidence_ids": {
                                "type": "array",
                                "items": {"type": "string"},
                                "uniqueItems": True,
                                "minItems": 1,
                                "maxItems": 10,
                            },
                        },
                        "required": [
                            "instrument_id",
                            "position",
                            "score",
                            "reason_codes",
                            "evidence_ids",
                        ],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["candidates"],
            "additionalProperties": False,
        }

    def _parse_final(
        self,
        output: dict[str, object],
        pool: tuple[InstrumentAssessment, ...],
        packet_by_id: dict[uuid.UUID, EvidencePacket],
    ) -> tuple[FinalCandidate, ...]:
        values = output.get("candidates")
        if not isinstance(values, list) or len(values) != self.config.requested_count:
            raise LlmRankingError("Final candidate count is invalid", ())
        pool_ids = {item.instrument_id for item in pool}
        candidates = []
        seen_ids: set[uuid.UUID] = set()
        seen_positions: set[int] = set()
        for value in values:
            if not isinstance(value, dict):
                raise LlmRankingError("Final candidate must be an object", ())
            instrument_id = uuid.UUID(str(value["instrument_id"]))
            position = int(value["position"])
            score = float(value["score"])
            reason_codes = tuple(str(item) for item in value["reason_codes"])
            evidence_ids = tuple(uuid.UUID(str(item)) for item in value["evidence_ids"])
            allowed = {
                link.evidence_link_id for link in packet_by_id[instrument_id].links
            } if instrument_id in packet_by_id else set()
            if (
                instrument_id not in pool_ids
                or instrument_id in seen_ids
                or position in seen_positions
                or not 0 <= score <= 100
                or not reason_codes
                or any(item not in _REASON_CODES for item in reason_codes)
                or len(set(reason_codes)) != len(reason_codes)
                or len(evidence_ids) > 10
                or any(item not in allowed for item in evidence_ids)
            ):
                raise LlmRankingError("Final candidate references are invalid", ())
            seen_ids.add(instrument_id)
            seen_positions.add(position)
            candidates.append(
                FinalCandidate(
                    instrument_id=instrument_id,
                    position=position,
                    score=score,
                    reason_codes=reason_codes,
                    evidence_ids=evidence_ids,
                )
            )
        expected_positions = set(range(1, self.config.requested_count + 1))
        if seen_positions != expected_positions:
            raise LlmRankingError("Final positions are not contiguous", ())
        return tuple(sorted(candidates, key=lambda item: item.position))


def _required_score(item: InstrumentAssessment) -> float:
    if item.score is None:
        raise LlmRankingError("Legacy assessment score is missing", ())
    return item.score
