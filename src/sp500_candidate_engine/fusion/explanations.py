from __future__ import annotations

import ipaddress
import json
import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from decimal import ROUND_HALF_EVEN, Decimal
from fractions import Fraction
from typing import ClassVar, Literal
from urllib.parse import parse_qsl, urlsplit
from uuid import UUID

from sp500_candidate_engine.database import _canonical_hash, _stable_uuid
from sp500_candidate_engine.fusion.policy import FusionResult
from sp500_candidate_engine.llm_preselection.asof import publication_bound
from sp500_candidate_engine.llm_preselection.enrichment_contract import document_from_payload
from sp500_candidate_engine.llm_preselection.evidence import EvidenceLink
from sp500_candidate_engine.llm_preselection.summaries import SUMMARY_VERSION, citation_summary
from sp500_candidate_engine.llm_preselection.temporal import (
    TEMPORAL_HARNESS_VERSION,
    provided_item,
    timestamp,
    validate_packet_data,
    validate_revision_time,
)

SCHEMA_VERSION = "candidate-explanation-v1"
EXTERNAL_SCHEMA_VERSION = "candidate-explanation-v3"
EXPLANATION_VERSIONS = {SCHEMA_VERSION, EXTERNAL_SCHEMA_VERSION}


class Snapshot:
    __pydantic_config__: ClassVar[dict[str, object]] = {"extra": "forbid"}


@dataclass(frozen=True)
class EvidenceExplanation(Snapshot):
    evidence_link_id: UUID
    source_snapshot_id: UUID
    source_kind: Literal["NEWS", "EARNINGS", "EVENT", "SEC_FILING", "SEC_FACT", "CORPORATE_ACTION"]
    criterion: Literal["earnings", "business", "event", "financial", "industry"]
    source_label: str | None
    source_available_at: datetime
    period_end: date | None
    summary: str
    source_url: str | None
    metadata_status: Literal["AVAILABLE", "PARTIAL"]


@dataclass(frozen=True)
class ExternalSourceExplanation(Snapshot):
    source_layer: Literal["LLM_SEARCH_VERIFIED"]
    source_url: str
    tool_response_hash: str
    evidence_hash: str
    artifact_key: str
    parent_accepted_at: str
    source_available_at: datetime
    source_local_date: date
    source_date_precision: Literal["DAY", "TIMESTAMP"]
    retrieved_at: datetime
    model_snapshot: str | None
    verification_method: Literal["NATIVE_SEARCH_PINNED_ARCHIVE"]


@dataclass(frozen=True)
class ExternalEvidenceExplanation(EvidenceExplanation):
    external_source: ExternalSourceExplanation


@dataclass(frozen=True)
class QuantExplanation(Snapshot):
    selected_in_source: bool
    selection_run_id: UUID
    score_semantics: Literal["PREDICTED_20D_RETURN"]
    score: float | None
    rank_overall: int | None
    position: int | None
    reason_codes: tuple[str, ...]
    summary: str


@dataclass(frozen=True)
class LlmExplanation(Snapshot):
    selected_in_source: bool
    selection_run_id: UUID
    score: float | None
    position: int | None
    supported_count: int | None
    weight_denominator: int | None
    summary_method: Literal["VALIDATED_ASSESSMENT", "DETERMINISTIC_CITATIONS", "NOT_IN_SOURCE"]
    summary: str
    sub_scores: dict[str, float | None]
    missing_reasons: dict[str, str]
    evidence: tuple[EvidenceExplanation | ExternalEvidenceExplanation, ...]


@dataclass(frozen=True)
class Contribution(Snapshot):
    numerator: int
    denominator: int


@dataclass(frozen=True)
class FusionExplanation(Snapshot):
    rrf_k: int
    quant_contribution: Contribution | None
    llm_contribution: Contribution | None
    rrf_numerator: int
    rrf_denominator: int
    position: int
    reason_codes: tuple[str, ...]
    sector_cap_relaxed_for_candidate: bool


@dataclass(frozen=True)
class CandidateExplanation(Snapshot):
    schema_version: Literal["candidate-explanation-v1", "candidate-explanation-v3"]
    status: Literal["RECORDED"]
    price_session_date: date
    cutoff_at: datetime
    execution_context_id: UUID
    summary: str
    quant: QuantExplanation
    llm: LlmExplanation
    fusion: FusionExplanation

    def __post_init__(self) -> None:
        timestamp(self.cutoff_at)
        if self.schema_version not in EXPLANATION_VERSIONS or self.status != "RECORDED":
            raise ValueError("Unsupported explanation contract")
        if any(
            not text.strip() or len(text) > 600
            for text in (
                self.summary,
                self.quant.summary,
                self.llm.summary,
            )
        ):
            raise ValueError("Explanation summaries must be nonempty and bounded")
        if len(self.llm.evidence) > 10 or len(
            {(item.evidence_link_id, item.criterion) for item in self.llm.evidence}
        ) != len(self.llm.evidence):
            raise ValueError("Invalid explanation citation count or duplicate criterion")
        for evidence in self.llm.evidence:
            if isinstance(evidence, ExternalEvidenceExplanation):
                external = evidence.external_source
                bound = publication_bound(external.parent_accepted_at, self.cutoff_at)
                if (
                    self.schema_version != EXTERNAL_SCHEMA_VERSION
                    or external.source_available_at > self.cutoff_at
                    or external.source_available_at
                    != bound.upper_bound_at
                    or external.source_local_date != bound.local_date
                    or external.source_date_precision != bound.precision
                    or external.source_url != evidence.source_url
                    or not re.fullmatch(r"[0-9a-f]{64}\.json", external.artifact_key)
                    or len(external.tool_response_hash) != 64
                    or len(external.evidence_hash) != 64
                ):
                    raise ValueError("Invalid external explanation witness")
            if (
                timestamp(evidence.source_available_at) > self.cutoff_at
                or not 1 <= len(evidence.summary.strip()) <= 600
                or (
                    evidence.source_label is not None and not 1 <= len(evidence.source_label) <= 256
                )
                or (
                    evidence.period_end is not None
                    and evidence.period_end
                    > (
                        self.price_session_date
                        if evidence.source_kind == "SEC_FACT"
                        else self.cutoff_at.date()
                    )
                )
                or self.llm.sub_scores.get(evidence.criterion) is None
                or (evidence.source_url is not None and safe_url(evidence.source_url) is None)
                or (
                    evidence.metadata_status == "AVAILABLE"
                    and (
                        evidence.source_label is None
                        or evidence.source_url is None
                        or (
                            evidence.source_kind in {"SEC_FILING", "SEC_FACT"}
                            and evidence.period_end is None
                        )
                    )
                )
            ):
                raise ValueError("Invalid scored explanation evidence")
        total = Fraction(0)
        for branch, contribution in (
            (self.quant, self.fusion.quant_contribution),
            (self.llm, self.fusion.llm_contribution),
        ):
            if branch.selected_in_source:
                if (
                    branch.position is None
                    or not 1 <= branch.position <= 20
                    or branch.score is None
                    or not math.isfinite(branch.score)
                    or contribution is None
                    or contribution != Contribution(1, self.fusion.rrf_k + branch.position)
                ):
                    raise ValueError("Explanation source contribution mismatch")
                total += Fraction(contribution.numerator, contribution.denominator)
            elif (
                branch.position is not None or branch.score is not None or contribution is not None
            ):
                raise ValueError("Absent explanation source must not contribute a score")
        if (
            self.fusion.rrf_k <= 0
            or not 1 <= self.fusion.position <= 20
            or self.fusion.rrf_denominator <= 0
            or total <= 0
            or total != Fraction(self.fusion.rrf_numerator, self.fusion.rrf_denominator)
            or self.fusion.sector_cap_relaxed_for_candidate
            != ("SECTOR_CAP_RELAXED" in self.fusion.reason_codes)
        ):
            raise ValueError("Explanation RRF mismatch")
        if self.llm.selected_in_source:
            supported = {key for key, value in self.llm.sub_scores.items() if value is not None}
            if (
                not 3 <= len(supported) <= 5
                or self.llm.supported_count != len(supported)
                or set(self.llm.sub_scores)
                != {
                    "earnings",
                    "business",
                    "event",
                    "financial",
                    "industry",
                }
                or set(self.llm.missing_reasons) != set(self.llm.sub_scores) - supported
                or any(
                    not reason.strip() or len(reason) > 600
                    for reason in self.llm.missing_reasons.values()
                )
                or any(
                    not math.isfinite(value) or not 0 <= value <= 100
                    for value in self.llm.sub_scores.values()
                    if value is not None
                )
                or supported != {item.criterion for item in self.llm.evidence}
                or self.llm.weight_denominator is None
                or not 1 <= self.llm.weight_denominator <= 100
                or self.llm.summary_method == "NOT_IN_SOURCE"
            ):
                raise ValueError("Explanation LLM coverage mismatch")
        elif (
            self.llm.sub_scores
            or self.llm.evidence
            or self.llm.missing_reasons
            or self.llm.supported_count is not None
            or self.llm.weight_denominator is not None
            or self.llm.summary_method != "NOT_IN_SOURCE"
        ):
            raise ValueError("Absent LLM explanation must not imply an assessment")
        if not self.quant.selected_in_source and (
            self.quant.rank_overall is not None or self.quant.reason_codes
        ):
            raise ValueError("Absent quantitative explanation contains source values")


def safe_url(value: object) -> str | None:
    if (
        not isinstance(value, str)
        or len(value) > 2048
        or "\\" in value
        or any(character.isspace() or ord(character) < 32 for character in value)
    ):
        return None
    try:
        parsed = urlsplit(value)
        hostname = parsed.hostname
        if (
            parsed.scheme != "https"
            or hostname is None
            or "." not in hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.port not in (None, 443)
            or parsed.fragment
            or hostname.endswith((".local", ".internal", ".localhost"))
            or any(
                key.lower()
                in {
                    "token",
                    "access_token",
                    "key",
                    "api_key",
                    "api-key",
                    "apikey",
                    "sig",
                    "signature",
                    "password",
                    "secret",
                    "authorization",
                }
                for key, _ in parse_qsl(parsed.query)
            )
        ):
            return None
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            return value
        return None
    except ValueError:
        return None


def explanation_config(
    rubric: Mapping[str, int],
    rationale_limit: int,
    *,
    verified_external: bool = False,
) -> dict[str, object]:
    if set(rubric) != {"earnings", "business", "event", "financial", "industry"}:
        raise ValueError("Unsupported explanation rubric")
    return {
        "schema_version": EXTERNAL_SCHEMA_VERSION if verified_external else SCHEMA_VERSION,
        "summary_version": SUMMARY_VERSION,
        "temporal_harness_version": TEMPORAL_HARNESS_VERSION,
        "rationale_characters": min(600, rationale_limit),
        "source_label_characters": 256,
        "max_evidence": 10,
        "rubric": dict(rubric),
    }


def _json_default(value: object) -> str:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError("Explanation contains a non-JSON value")


def explanation_payload(explanation: CandidateExplanation) -> dict[str, object]:
    return json.loads(json.dumps(asdict(explanation), default=_json_default, ensure_ascii=True))


def explanation_output_hash(snapshots: Mapping[str, object]) -> str:
    def normalize(value: object) -> object:
        # JSONB/consumers may round-trip an integral float as an integer.
        if isinstance(value, float) and value.is_integer():
            return int(value)
        if isinstance(value, Mapping):
            return {key: normalize(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [normalize(item) for item in value]
        return value

    return _canonical_hash(normalize(snapshots))


def _project_evidence(
    row: dict,
    *,
    context: dict[str, object],
    target_session: date,
    rationale_limit: int,
    llm_ranking_run_id: UUID,
) -> tuple[dict[str, float | None], dict[str, str], tuple[EvidenceExplanation, ...]]:
    packet, citations, links = row["packet"], row["criterion_evidence"], row["evidence_links"]
    if (
        not isinstance(packet, dict)
        or _canonical_hash(packet) != row["packet_hash"]
        or not isinstance(packet.get("identity"), dict)
        or packet["identity"].get("instrument_id") != str(row["instrument_id"])
        or packet["identity"].get("issuer_id") != str(row["issuer_id"])
        or packet.get("execution_context_id") != str(context["execution_context_id"])
        or packet.get("target_session") != target_session.isoformat()
        or timestamp(packet.get("cutoff_at")) != timestamp(context["cutoff_at"])
        or not isinstance(citations, list)
        or not 1 <= len(citations) <= 10
        or not isinstance(links, list)
    ):
        raise ValueError("Explanation packet identity/hash mismatch")
    scores, missing = row["sub_scores"], row["missing_reasons"]
    if packet.get("schema_version") == "4" and not packet.get("llm_search_manifest_hash"):
        raise ValueError("Search Fusion source is missing its admitted tool manifest")
    if not isinstance(scores, dict) or not isinstance(missing, dict):
        raise ValueError("Invalid explanation assessment")
    by_id = {str(link["evidence_link_id"]): link for link in links}
    if len(by_id) != len(links) or any(
        not link["manifest_member"] or str(link["instrument_id"]) != str(row["instrument_id"])
        for link in links
    ):
        raise ValueError("Explanation packet contains invalid source lineage")
    for link in links:
        validate_revision_time(
            source_kind=link["source_kind"],
            revision_no=link["revision_no"],
            revision_observed_at=link["revision_observed_at"],
            cutoff_at=timestamp(context["cutoff_at"]),
        )
    validate_packet_data(
        packet,
        instrument_id=UUID(str(row["instrument_id"])),
        packet_hash=row["packet_hash"],
        links=tuple(
            EvidenceLink(
                UUID(str(link["evidence_link_id"])),
                UUID(str(link["source_snapshot_id"])),
                link["source_kind"],
                link["entity_key"],
                timestamp(link["source_available_at"]),
                timestamp(link["observed_at"]) if link["observed_at"] is not None else None,
                timestamp(link["event_at"]) if link.get("event_at") is not None else None,
            )
            for link in links
        ),
        cutoff_at=timestamp(context["cutoff_at"]),
        target_session=target_session,
        execution_context_id=UUID(str(context["execution_context_id"])),
        knowledge_mode=str(context["knowledge_mode"]),
    )
    evidence = []
    for citation in citations:
        criterion, reason = citation["criterion"], citation["reason"]
        if (
            criterion not in scores
            or not isinstance(reason, str)
            or not 1 <= len(reason.strip()) <= rationale_limit
            or citation["evidence_link_id"] not in row["evidence_ids"]
        ):
            raise ValueError("Invalid explanation criterion reference")
        link = by_id.get(citation["evidence_link_id"])
        if (
            link is None
            or not link["manifest_member"]
            or (str(link["instrument_id"]) != str(row["instrument_id"]))
        ):
            raise ValueError("Explanation evidence is outside its instrument/manifest")
        expected_id = _stable_uuid(
            "llm-run-evidence-link",
            (
                f"{llm_ranking_run_id}:{row['instrument_id']}:{link['source_kind']}:"
                f"{link['entity_key']}:{link['source_snapshot_id']}"
            ),
        )
        if str(link["evidence_link_id"]) != str(expected_id):
            raise ValueError("Explanation evidence snapshot/ranking identity mismatch")
        item = provided_item(packet, link["source_kind"], link["entity_key"])
        source_layer = citation.get("source_layer", "DB_PACKET")
        external = None
        if source_layer == "LLM_SEARCH_VERIFIED":
            if packet.get("schema_version") != "4" or link["source_kind"] != "SEC_FILING":
                raise ValueError("External explanation citation has no provided parent filing")
            external = document_from_payload(
                item.get("search_evidence"),
                cik=packet["identity"]["cik"],
                filing=item,
                cutoff_at=timestamp(context["cutoff_at"]),
                knowledge_mode=str(context["knowledge_mode"]),
            )
            if citation.get("search_evidence_hash") != external.evidence_hash:
                raise ValueError("External explanation citation hash mismatch")
        elif source_layer != "DB_PACKET" or citation.get("search_evidence_hash") is not None:
            raise ValueError("Unsupported explanation evidence origin")
        if scores[criterion] is None:
            continue
        label = item.get("title")
        period = item.get("period_end")
        complete_label = bool(label)
        if link["source_kind"] in {"SEC_FILING", "SEC_FACT"}:
            fields = (
                ("form_type", "period_end")
                if link["source_kind"] == "SEC_FILING"
                else (
                    "concept",
                    "period_end",
                    "value_numeric",
                    "unit",
                )
            )
            parts = [str(item[key]) for key in fields if item.get(key) is not None]
            label = " | ".join(parts) or None
            complete_label = all(item.get(key) is not None for key in fields)
        if label is not None and not isinstance(label, str):
            raise ValueError("Invalid source label")
        url = (
            external.source_url
            if external
            else safe_url(item.get("source_url") or item.get("article_url"))
        )
        projected = EvidenceExplanation(
            UUID(str(link["evidence_link_id"])),
            UUID(str(link["source_snapshot_id"])),
            link["source_kind"],
            criterion,
            label[:256] if label else None,
            timestamp(link["source_available_at"]),
            date.fromisoformat(str(period)) if period is not None else None,
            reason,
            url,
            "AVAILABLE" if complete_label and url else "PARTIAL",
        )
        if external:
            projected = ExternalEvidenceExplanation(
                **asdict(projected),
                external_source=ExternalSourceExplanation(
                    "LLM_SEARCH_VERIFIED",
                    external.source_url,
                    external.tool_response_hash,
                    external.evidence_hash,
                    external.artifact_key,
                    external.parent_accepted_at,
                    timestamp(external.source_available_at),
                    date.fromisoformat(external.source_local_date),
                    external.source_date_precision,
                    timestamp(external.retrieved_at),
                    external.model_snapshot,
                    "NATIVE_SEARCH_PINNED_ARCHIVE",
                ),
            )
        evidence.append(projected)
    return scores, missing, tuple(evidence)


def build_explanations(
    result: FusionResult,
    *,
    quant: dict[str, object],
    llm: dict[str, object],
    context: dict[str, object],
    target_session: date,
    rubric: dict[str, int],
    rationale_limit: int,
    rrf_k: int,
) -> dict[str, CandidateExplanation]:
    rows = llm["candidates"]
    if not isinstance(rows, list):
        raise ValueError("Invalid explanation LLM source")
    llm_rows = {str(row["instrument_id"]): row for row in rows}
    snapshots = {}
    for candidate in result.candidates:
        q, llm_input = candidate.quant, candidate.llm
        quant_summary = (
            (
                f"MEDIUM_20D predicted return {q.score:+.2%}; overall rank {q.original_rank}; "
                f"Quant Top20 position {q.position}."
            )
            if q
            else "Not selected in source Quant Top20."
        )
        quant_explanation = QuantExplanation(
            q is not None,
            UUID(str(quant["selection_run_id"])),
            "PREDICTED_20D_RETURN",
            q.score if q else None,
            q.original_rank if q else None,
            q.position if q else None,
            q.reason_codes if q else (),
            quant_summary,
        )
        if llm_input:
            row = llm_rows[str(candidate.instrument_id)]
            if row["packet"].get("schema_version") != llm["evidence_schema_version"]:
                raise ValueError("Explanation evidence schema mismatch")
            scores, missing, evidence = _project_evidence(
                row,
                context=context,
                target_session=target_session,
                rationale_limit=rationale_limit,
                llm_ranking_run_id=UUID(str(llm["llm_ranking_run_id"])),
            )
            if (
                set(scores) != set(rubric)
                or set(missing) != {key for key, value in scores.items() if value is None}
                or any(
                    not isinstance(reason, str) or not 1 <= len(reason.strip()) <= rationale_limit
                    for reason in missing.values()
                )
            ):
                raise ValueError("Explanation criteria/missing reasons mismatch")
            supported = {key: value for key, value in scores.items() if value is not None}
            if any(
                type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 100
                for value in supported.values()
            ):
                raise ValueError("Invalid explanation criterion score")
            denominator = sum(rubric[key] for key in supported)
            if denominator <= 0 or row["weight_denominator"] != denominator:
                raise ValueError("Explanation weight denominator mismatch")
            score = (
                sum(
                    (Decimal(str(value)) * rubric[key] for key, value in supported.items()),
                    Decimal(0),
                )
                / denominator
            )
            if (
                float(score.quantize(Decimal("0.0001"), rounding=ROUND_HALF_EVEN))
                != llm_input.score
            ):
                raise ValueError("Explanation assessment score mismatch")
            summary = citation_summary(scores, row["criterion_evidence"], limit=rationale_limit)
            # Free-form prose is reused only when it exactly matches the grounded projection.
            assessment_config = llm.get("assessment_config")
            deterministic = (
                isinstance(assessment_config, dict)
                and assessment_config.get("summary_version") == SUMMARY_VERSION
            )
            method = (
                "VALIDATED_ASSESSMENT"
                if row["rationale"] == summary and not deterministic
                else "DETERMINISTIC_CITATIONS"
            )
            llm_explanation = LlmExplanation(
                True,
                UUID(str(llm["run_id"])),
                llm_input.score,
                llm_input.position,
                row["supported_count"],
                row["weight_denominator"],
                method,
                summary,
                scores,
                missing,
                evidence,
            )
        else:
            llm_explanation = LlmExplanation(
                False,
                UUID(str(llm["run_id"])),
                None,
                None,
                None,
                None,
                "NOT_IN_SOURCE",
                "Not selected in source LLM Top20.",
                {},
                {},
                (),
            )
        fusion = FusionExplanation(
            rrf_k,
            Contribution(1, rrf_k + q.position) if q else None,
            Contribution(1, rrf_k + llm_input.position) if llm_input else None,
            candidate.rrf.numerator,
            candidate.rrf.denominator,
            candidate.position,
            candidate.reason_codes,
            "SECTOR_CAP_RELAXED" in candidate.reason_codes,
        )
        snapshot = CandidateExplanation(
            EXTERNAL_SCHEMA_VERSION if llm["evidence_schema_version"] == "4" else SCHEMA_VERSION,
            "RECORDED",
            target_session,
            timestamp(context["cutoff_at"]),
            UUID(str(context["execution_context_id"])),
            f"{quant_summary} {llm_explanation.summary_method}: "
            f"LLM score {llm_input.score if llm_input else 'not in source'}, position "
            f"{llm_input.position if llm_input else 'not in source'}. "
            f"RRF k={rrf_k}: {candidate.rrf.numerator}/{candidate.rrf.denominator}; "
            f"Fusion position {candidate.position}.",
            quant_explanation,
            llm_explanation,
            fusion,
        )
        snapshots[str(candidate.instrument_id)] = snapshot
    return snapshots


def validate_stored_explanation(
    explanation: CandidateExplanation,
    candidate: Mapping[str, object],
    *,
    context_id: UUID,
    target_session: date,
    cutoff_at: datetime,
    rrf_k: int,
    quant_id: UUID | None,
    llm_id: UUID | None,
) -> None:
    if (
        explanation.execution_context_id != context_id
        or explanation.price_session_date != target_session
        or explanation.cutoff_at != cutoff_at
        or explanation.quant.selection_run_id != quant_id
        or explanation.llm.selection_run_id != llm_id
        or explanation.fusion.rrf_k != rrf_k
    ):
        raise ValueError("Stored explanation run identity mismatch")
    actual = (
        explanation.quant.selected_in_source,
        explanation.quant.score,
        explanation.quant.position,
        explanation.quant.rank_overall,
        explanation.llm.selected_in_source,
        explanation.llm.score,
        explanation.llm.position,
        explanation.fusion.position,
        explanation.fusion.rrf_numerator,
        explanation.fusion.rrf_denominator,
        list(explanation.fusion.reason_codes),
    )
    expected = tuple(
        candidate[key]
        for key in (
            "selected_by_quant",
            "quant_predicted_return",
            "quant_rank",
            "quant_rank_overall",
            "selected_by_llm",
            "llm_score",
            "llm_rank",
            "position",
            "rrf_numerator",
            "rrf_denominator",
            "reason_codes",
        )
    )
    refs = candidate["source_evidence_refs"]
    if not isinstance(refs, (list, tuple)):
        raise ValueError("Invalid stored candidate evidence references")
    if actual != expected or not {
        str(item.evidence_link_id) for item in explanation.llm.evidence
    } <= {str(value) for value in refs}:
        raise ValueError("Stored explanation differs from the selected candidate")
