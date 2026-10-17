from __future__ import annotations

import json
import math
import uuid
from copy import deepcopy
from dataclasses import replace
from decimal import ROUND_HALF_EVEN, Decimal

from sp500_candidate_engine.llm_preselection.evidence import EvidencePacket
from sp500_candidate_engine.llm_preselection.ranker import (
    AzureOpenAIPreselectionRanker,
    FinalCandidate,
    InstrumentAssessment,
    LlmRankingError,
    RankingResult,
)


class EventPreselectionRanker(AzureOpenAIPreselectionRanker):
    async def rank(
        self, *, llm_ranking_run_id: uuid.UUID, packets: tuple[EvidencePacket, ...]
    ) -> RankingResult:
        assessments: list[InstrumentAssessment] = []
        attempts = []
        ordered = sorted(packets, key=lambda packet: packet.instrument_id.hex)
        try:
            for start in range(0, len(ordered), self.config.batch_size):
                batch = ordered[start:start + self.config.batch_size]
                batch_no = start // self.config.batch_size
                messages = self._assessment_messages(batch)
                batch_attempts = 0
                while batch_attempts < self.config.max_attempts:
                    output, output_hash, calls = await self._call(
                        run_id=llm_ranking_run_id, stage="INSTRUMENT_BATCH", batch_no=batch_no,
                        messages=messages, attempt_offset=batch_attempts,
                        schema_name="event_assessments_v2", schema=self._assessment_schema(batch),
                        execution_context_id=(
                            uuid.UUID(str(batch[0].packet["execution_context_id"]))
                            if "execution_context_id" in batch[0].packet else None
                        ),
                    )
                    attempts.extend(calls)
                    batch_attempts += len(calls)
                    try:
                        assessments.extend(self._parse_assessments(
                            output=output, output_hash=output_hash, batch_no=batch_no, packets=batch
                        ))
                        break
                    except (KeyError, TypeError, ValueError, OverflowError) as error:
                        attempts[-1] = replace(
                            attempts[-1], status="FAILED", error_code="OUTPUT_VALIDATION_FAILED"
                        )
                        if batch_attempts >= self.config.max_attempts:
                            raise LlmRankingError(
                                "Event assessment output is malformed", ()
                            ) from error
                        messages = [
                            *self._assessment_messages(batch),
                            {"role": "user", "content": (
                                "The previous response failed semantic validation. Return the full "
                                "batch again, using only evidence_link_id values from each SAME "
                                "instrument's evidence list, never event_revision_id, snapshot ID "
                                "or another issuer's evidence. Supported scores require a citation "
                                "and missing_reasons=null. Unsupported scores must be null with "
                                "a missing reason. Do not invent evidence or force eligibility."
                            )},
                        ]
        except LlmRankingError as error:
            raise LlmRankingError(str(error), tuple([*attempts, *error.attempts])) from error
        ordered_assessments = sorted(
            assessments,
            key=lambda item: (
                item.score is None, -(item.score if item.score is not None else 0),
                item.instrument_id.hex,
            ),
        )
        ranked = tuple(
            replace(item, first_stage_rank=rank)
            for rank, item in enumerate(ordered_assessments, 1)
        )
        candidates = []
        for item in ranked:
            if item.score is None:
                continue
            candidates.append(FinalCandidate(
                item.instrument_id, len(candidates) + 1, item.score,
                item.reason_codes, item.evidence_ids,
            ))
            if len(candidates) == 20:
                break
        return RankingResult(ranked, tuple(candidates), tuple(attempts))

    def _assessment_messages(self, packets: list[EvidencePacket]) -> list[dict[str, str]]:
        return [
            {
                "role": "system",
                "content": (
                    "Evaluate only supplied point-in-time company evidence. Do not use external "
                    "knowledge, web search, prices, quantitative scores or investment advice. "
                    "Return each instrument once. Score a criterion only when substantive supplied "
                    "evidence supports it; filing existence or identity alone is not support. "
                    "Use null and a missing reason otherwise. Provide a specific evidence ID and "
                    "bounded reason for every supported criterion. Do not invent confidence, "
                    "probability, risk scores or a total score. "
                    f"Rubric weights: {self.config.rubric}. "
                    f"Prompt version: {self.config.prompt_version}."
                ),
            },
            {
                "role": "user",
                "content": json.dumps([{
                    "instrument_id": str(packet.instrument_id),
                    "issuer_id": str(packet.issuer_id),
                    "packet": packet.packet,
                    "evidence": [{
                        "evidence_link_id": str(link.citation_id or link.evidence_link_id),
                        "source_kind": link.source_kind,
                        "entity_key": link.entity_key,
                    } for link in packet.links if link.source_kind not in {
                        "UNIVERSE", "INSTRUMENT_STATE", "DAILY_BAR"
                    }],
                } for packet in packets], sort_keys=True, ensure_ascii=True),
            },
        ]

    def _assessment_schema(self, packets: list[EvidencePacket]) -> dict[str, object]:
        criteria = list(self.config.rubric)
        properties = {
            "instrument_id": {"type": "string", "enum": [str(p.instrument_id) for p in packets]},
            "scores": {
                "type": "object",
                "properties": {key: {"type": ["number", "null"], "minimum": 0, "maximum": 100}
                               for key in criteria},
                "required": criteria, "additionalProperties": False,
            },
            "missing_reasons": {
                "type": "object",
                "properties": {key: {"type": ["string", "null"],
                                    "maxLength": self.config.limits.rationale_characters}
                               for key in criteria},
                "required": criteria, "additionalProperties": False,
            },
            "evidence_quality": {"type": "string", "enum": ["HIGH", "MEDIUM", "LOW"]},
            "uncertainty": {"type": "string", "enum": ["LOW", "MEDIUM", "HIGH"]},
            "summary": {"type": "string", "maxLength": self.config.limits.rationale_characters},
            "evidence": {
                "type": "array", "maxItems": 10,
                "items": {
                    "type": "object",
                    "properties": {
                        "evidence_link_id": {"type": "string"},
                        "criterion": {"type": "string", "enum": criteria},
                        "reason": {"type": "string", "minLength": 1,
                                   "maxLength": self.config.limits.rationale_characters},
                    },
                    "required": ["evidence_link_id", "criterion", "reason"],
                    "additionalProperties": False,
                },
            },
        }
        variants = []
        for packet in packets:
            variant = deepcopy(properties)
            variant["instrument_id"] = {"type": "string", "enum": [str(packet.instrument_id)]}
            evidence_ids = [
                str(link.citation_id or link.evidence_link_id)
                for link in packet.links if link.source_kind not in {
                    "UNIVERSE", "INSTRUMENT_STATE", "DAILY_BAR"
                }
            ]
            if evidence_ids:
                variant["evidence"]["items"]["properties"]["evidence_link_id"] = {
                    "type": "string", "enum": evidence_ids,
                }
            else:
                variant["evidence"]["maxItems"] = 0
            variants.append({
                "type": "object", "properties": variant, "required": list(variant),
                "additionalProperties": False,
            })
        return {
            "type": "object",
            "properties": {"assessments": {
                "type": "array", "minItems": len(packets), "maxItems": len(packets),
                "items": {"anyOf": variants},
            }},
            "required": ["assessments"], "additionalProperties": False,
        }

    def _parse_assessments(
        self, *, output: dict[str, object], output_hash: str,
        batch_no: int, packets: list[EvidencePacket],
    ) -> list[InstrumentAssessment]:
        values = output.get("assessments")
        if set(output) != {"assessments"} or not isinstance(values, list):
            raise ValueError("Invalid event assessment envelope")
        packet_by_id = {packet.instrument_id: packet for packet in packets}
        seen = set()
        parsed = []
        for value in values:
            if not isinstance(value, dict) or set(value) != {
                "instrument_id", "scores", "missing_reasons", "evidence_quality",
                "uncertainty", "summary", "evidence",
            }:
                raise ValueError("Invalid event assessment fields")
            instrument_id = uuid.UUID(value["instrument_id"])
            if instrument_id not in packet_by_id or instrument_id in seen:
                raise ValueError("Invalid event assessment instrument")
            seen.add(instrument_id)
            scores = value["scores"]
            missing = value["missing_reasons"]
            if not isinstance(scores, dict) or not isinstance(missing, dict) \
                    or set(scores) != set(self.config.rubric) \
                    or set(missing) != set(self.config.rubric):
                raise ValueError("Event criteria do not match the policy")
            evidence = value["evidence"]
            if not isinstance(evidence, list) or len(evidence) > 10:
                raise ValueError("Invalid criterion evidence")
            allowed = {
                str(link.citation_id or link.evidence_link_id): link.evidence_link_id
                for link in packet_by_id[instrument_id].links
                if link.source_kind not in {"UNIVERSE", "INSTRUMENT_STATE", "DAILY_BAR"}
            }
            for citation in evidence:
                if (
                    not isinstance(citation, dict)
                    or set(citation) != {"evidence_link_id", "criterion", "reason"}
                    or citation["evidence_link_id"] not in allowed
                    or citation["criterion"] not in scores
                    or not isinstance(citation["reason"], str)
                    or not 1 <= len(citation["reason"].strip())
                    <= self.config.limits.rationale_characters
                ):
                    raise ValueError("Invalid criterion evidence reference")
            supported = []
            for criterion, score in scores.items():
                if score is None:
                    if not isinstance(missing[criterion], str) or not missing[criterion].strip() \
                            or len(missing[criterion]) > self.config.limits.rationale_characters:
                        raise ValueError("Missing criterion requires a bounded reason")
                else:
                    if type(score) not in {int, float} or not math.isfinite(score) \
                            or not 0 <= score <= 100 or missing[criterion] is not None \
                            or not any(item["criterion"] == criterion for item in evidence):
                        raise ValueError("Score requires valid evidence and no missing reason")
                    supported.append(criterion)
            denominator = sum(self.config.rubric[key] for key in supported)
            score = None
            if len(supported) >= 3:
                weighted = sum(
                    (Decimal(str(scores[key])) * self.config.rubric[key] for key in supported),
                    Decimal(0),
                )
                score = float((weighted / denominator).quantize(
                    Decimal("0.0001"), rounding=ROUND_HALF_EVEN
                ))
            quality, uncertainty = value["evidence_quality"], value["uncertainty"]
            summary = value["summary"]
            if quality not in {"HIGH", "MEDIUM", "LOW"} or uncertainty not in {
                "LOW", "MEDIUM", "HIGH"
            } or not isinstance(summary, str) or (
                len(summary) > self.config.limits.rationale_characters
            ):
                raise ValueError("Invalid evidence quality or summary")
            normalized_evidence = tuple({
                **citation, "evidence_link_id": str(allowed[citation["evidence_link_id"]])
            } for citation in evidence)
            parsed.append(InstrumentAssessment(
                instrument_id, batch_no, 1, score,
                {key: float(item) if item is not None else None for key, item in scores.items()},
                quality, uncertainty,
                ("EVIDENCE_BACKED",) if score is not None else ("INSUFFICIENT_EVIDENCE",),
                summary, tuple(sorted({uuid.UUID(item["evidence_link_id"])
                                       for item in normalized_evidence},
                                      key=lambda item: item.hex)),
                output_hash, normalized_evidence,
                {key: reason for key, reason in missing.items() if reason is not None},
                denominator, len(supported),
            ))
        if seen != set(packet_by_id):
            raise ValueError("Every supplied instrument must be assessed")
        return parsed
