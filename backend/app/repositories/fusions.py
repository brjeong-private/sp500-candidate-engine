from __future__ import annotations

import logging
from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException
from pydantic import TypeAdapter, ValidationError

from backend.app.pagination import date_filters, decode_cursor, encode_cursor, page_limit
from backend.app.repositories.base import ReadRepository
from backend.app.repositories.candidates import CandidateRepository
from backend.app.repositories.llm_preselections import LLMPreselectionRepository
from backend.app.schemas.common import Page
from backend.app.schemas.explanations import (
    CandidateExplanationView,
    FusionExplanations,
    FusionRunWithReasons,
    FusionSelectionReasons,
    LLMPreselectionWithReasons,
)
from backend.app.schemas.fusions import FusionRun
from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.fusion.explanations import (
    EXPLANATION_VERSIONS,
    EXTERNAL_SCHEMA_VERSION,
    SCHEMA_VERSION,
    CandidateExplanation,
    explanation_output_hash,
    validate_stored_explanation,
)

logger = logging.getLogger(__name__)
_EXPLANATION_ADAPTER = TypeAdapter(CandidateExplanation)
_V1_FIELDS = frozenset({
    "instrument_id", "issuer_id", "ticker", "sector", "position",
    "quant_rank", "quant_rank_overall", "quant_predicted_return",
    "llm_rank", "llm_assessment_rank", "llm_score", "rrf_score",
    "rrf_numerator", "rrf_denominator", "selected_by_quant", "selected_by_llm",
    "quality_status", "risk_status", "reason_codes", "source_evidence_refs",
})


def _v1_run(row: dict) -> FusionRun:
    return FusionRun.model_validate({
        **row, "candidates": [
            {key: value for key, value in candidate.items()
             if key in _V1_FIELDS or key == "company_name"}
            for candidate in row["candidates"]
        ],
    })

_COLUMNS = """
    r.fusion_run_id, r.execution_context_id, r.quant_selection_run_id, r.llm_preselection_run_id,
    r.price_session_date, r.cutoff_at, r.generated_at, r.model_purpose, r.selection_type,
    r.policy_version, r.config_hash, r.rrf_k, r.requested_count, r.selected_count,
    r.union_count, r.status, r.failure_code, r.sector_cap_relaxed, r.provenance,
    r.payload_hash, r.created_at,
    COALESCE((SELECT jsonb_agg(
                  candidate.candidate || jsonb_build_object('company_name', member.security_name)
                  ORDER BY candidate.position)
              FROM selection.fusion_candidate candidate
              LEFT JOIN selection.selection_run source
                  ON source.selection_run_id = r.quant_selection_run_id
              LEFT JOIN analytics.scoring_run scoring
                  ON scoring.scoring_run_id = source.scoring_run_id
              LEFT JOIN ref.universe_member member
                  ON member.universe_version_id = scoring.universe_version_id
                 AND member.instrument_id = candidate.instrument_id
              WHERE candidate.fusion_run_id = r.fusion_run_id), '[]'::jsonb) AS candidates
"""


class FusionReadRepository(ReadRepository):
    def get_run(self, run_id: UUID) -> FusionRun:
        rows = self.fetch(
            f"SELECT {_COLUMNS} FROM selection.fusion_run r WHERE r.fusion_run_id = %s",
            [run_id],
        )
        if not rows:
            raise HTTPException(404, "Fusion run not found")
        return _v1_run(rows[0])

    def list_runs(
        self, *, exact_date: date | None = None, start_date: date | None = None,
        end_date: date | None = None, quant_selection_run_id: UUID | None = None,
        policy_version: str | None = None, config_hash: str | None = None,
        cursor: str | None = None, limit: int = 100,
    ) -> Page[FusionRun]:
        page_limit(limit)
        start, end = date_filters(exact_date, start_date, end_date)
        filters = {
            "start": start, "end": end, "quant": quant_selection_run_id,
            "policy": policy_version, "config": config_hash,
        }
        position = decode_cursor(cursor, "fusion-selections", filters, 3)
        anchor = None
        boundary = ""
        boundary_parameters: list[object] = []
        if position is not None:
            try:
                anchor = datetime.fromisoformat(position[0])
                session = date.fromisoformat(position[1])
                run_id = UUID(position[2])
                if anchor.tzinfo is None:
                    raise ValueError
            except ValueError:
                raise HTTPException(422, "Invalid Fusion cursor") from None
            boundary = "WHERE (r.price_session_date, r.fusion_run_id) < (%s, %s)"
            boundary_parameters = [session, run_id]
        conditions = ["r.status = 'SUCCEEDED'", "r.created_at <= boundary.anchor"]
        parameters: list[object] = [anchor]
        if start is not None:
            conditions.append("r.price_session_date BETWEEN %s AND %s")
            parameters.extend([start, end])
        if quant_selection_run_id is not None:
            conditions.append("r.quant_selection_run_id = %s")
            parameters.append(quant_selection_run_id)
        for column, value in (("policy_version", policy_version), ("config_hash", config_hash)):
            if value is not None:
                conditions.append(f"r.{column} = %s")
                parameters.append(value)
        parameters.extend([*boundary_parameters, limit + 1])
        rows = self.fetch(f"""
            WITH boundary AS (
                SELECT COALESCE(%s::timestamptz, CURRENT_TIMESTAMP) AS anchor
            ), ranked AS (
                SELECT r.*, boundary.anchor AS _anchor,
                    ROW_NUMBER() OVER (PARTITION BY r.price_session_date
                        ORDER BY r.generated_at DESC, r.created_at DESC, r.fusion_run_id DESC) AS n
                FROM selection.fusion_run r CROSS JOIN boundary
                WHERE {" AND ".join(conditions)}
            ), selected AS (
                SELECT * FROM ranked WHERE n = 1
            )
            SELECT {_COLUMNS}, r._anchor FROM selected r {boundary}
            ORDER BY r.price_session_date DESC, r.fusion_run_id DESC LIMIT %s
        """, parameters)
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(
                "fusion-selections", filters,
                [str(last["_anchor"]), str(last["price_session_date"]), str(last["fusion_run_id"])],
            )
        items = []
        for row in rows[:limit]:
            row.pop("_anchor", None)
            items.append(_v1_run(row))
        return Page[FusionRun](items=items, next_cursor=next_cursor)

    def handoff(self, run_id: UUID) -> dict[str, object]:
        run = self.get_run(run_id)
        if run.status != "SUCCEEDED":
            raise HTTPException(409, "Only successful Fusion Top 20 can be handed off")
        data = run.model_dump(mode="json")
        envelope: dict[str, object] = {
            "contract_version": "fusion-top20-v1",
            "selection_type": "FUSION", "model_purpose": "MEDIUM_20D",
            "selection_run_id": str(run.fusion_run_id),
            "price_session_date": data["price_session_date"], "cutoff_at": data["cutoff_at"],
            "execution_context_id": str(run.execution_context_id),
            "quant_selection_run_id": str(run.quant_selection_run_id),
            "llm_preselection_run_id": str(run.llm_preselection_run_id),
            "policy_version": run.policy_version, "config_hash": run.config_hash,
            "rrf_k": run.rrf_k,
            "requested_count": 20, "selected_count": 20, "status": "SUCCEEDED",
            "candidates": [item.model_dump(mode="json", include=set(_V1_FIELDS))
                           for item in run.candidates],
        }
        envelope["payload_hash"] = _canonical_hash(envelope)
        return envelope

    def with_reasons(self, run: FusionRun) -> FusionRunWithReasons:
        snapshots = self.explanations(run.fusion_run_id)
        try:
            if not run.candidates:
                return FusionRunWithReasons(**run.model_dump(), selection_reasons=[])
            if run.quant_selection_run_id is None or run.llm_preselection_run_id is None:
                raise ValueError("Fusion source run identity is missing")
            quantitative = CandidateRepository(self.database).list_candidates(
                selection_run_id=run.quant_selection_run_id, limit=20, include_deleted=True,
            )
            llm = LLMPreselectionRepository(self.database).get_preselection(
                run.llm_preselection_run_id
            )
            if (
                quantitative.next_cursor is not None or len(quantitative.items) != 20
                or llm.status != "SUCCEEDED" or llm.ranking_status != "SUCCEEDED"
                or llm.selected_count != 20 or len(llm.candidates) != 20
                or llm.execution_context_id != run.execution_context_id
                or llm.price_session_date != run.price_session_date
                or llm.cutoff_at != run.cutoff_at
            ):
                raise ValueError("Fusion source result identity/status mismatch")
            assessments = self.fetch(
                """
                SELECT candidate.instrument_id, assessment.rationale, assessment.uncertainty
                FROM selection.llm_preselection_candidate candidate
                JOIN selection.llm_preselection_run source ON source.run_id = candidate.run_id
                JOIN analytics.llm_instrument_assessment assessment
                  ON assessment.llm_ranking_run_id = source.llm_ranking_run_id
                 AND assessment.instrument_id = candidate.instrument_id
                WHERE source.run_id = %s
                """,
                [run.llm_preselection_run_id],
            )
            assessment_by_id = {row["instrument_id"]: row for row in assessments}
            quant_by_id = {item.instrument_id: item for item in quantitative.items}
            llm_by_id = {item.instrument_id: item for item in llm.candidates}
            if (
                len(quant_by_id) != 20 or len(llm_by_id) != 20
                or len(assessments) != 20 or assessment_by_id.keys() != llm_by_id.keys()
                or any(
                    item.selection_run_id != run.quant_selection_run_id
                    or item.status != "SUCCEEDED" or item.model_purpose != "MEDIUM_20D"
                    or item.price_session_date != run.price_session_date
                    or item.cutoff_at != run.cutoff_at
                    for item in quantitative.items
                )
            ):
                raise ValueError("Fusion source candidate set mismatch")
            snapshot_by_id = {item.instrument_id: item for item in snapshots.candidates}
            reasons = []
            for candidate in run.candidates:
                quant_candidate = quant_by_id.get(candidate.instrument_id)
                llm_candidate = llm_by_id.get(candidate.instrument_id)
                if (
                    candidate.selected_by_quant != (quant_candidate is not None)
                    or candidate.selected_by_llm != (llm_candidate is not None)
                    or (quant_candidate is not None and (
                        quant_candidate.issuer_id != candidate.issuer_id
                        or quant_candidate.position != candidate.quant_rank
                        or quant_candidate.rank_overall != candidate.quant_rank_overall
                        or quant_candidate.predicted_return != candidate.quant_predicted_return
                    ))
                    or (llm_candidate is not None and (
                        llm_candidate.position != candidate.llm_rank
                        or llm_candidate.first_stage_rank != candidate.llm_assessment_rank
                        or llm_candidate.score != candidate.llm_score
                        or set(item.evidence_link_id for item in llm_candidate.evidence)
                        != set(candidate.source_evidence_refs)
                    ))
                ):
                    raise ValueError("Fusion candidate/source score or evidence mismatch")
                snapshot = snapshot_by_id[candidate.instrument_id]
                reasons.append(FusionSelectionReasons(
                    **snapshot.model_dump(),
                    source="STORED_SNAPSHOT" if snapshot.status == "RECORDED"
                    else "PINNED_SOURCE_RESULTS",
                    quantitative=quant_candidate,
                    llm=LLMPreselectionWithReasons(
                        **{
                            **llm_candidate.model_dump(),
                            **assessment_by_id[candidate.instrument_id],
                        }
                    ) if llm_candidate is not None else None,
                    fusion_summary=(
                        f"정량 후보 순위 {candidate.quant_rank}; "
                        f"LLM 후보 순위 {candidate.llm_rank}; RRF k={run.rrf_k}: "
                        f"{candidate.rrf_numerator}/{candidate.rrf_denominator}; "
                        f"최종 후보 {candidate.position}위. "
                        f"선정 사유: {', '.join(candidate.reason_codes)}."
                    ),
                ))
            return FusionRunWithReasons(**run.model_dump(), selection_reasons=reasons)
        except HTTPException as error:
            if error.status_code != 404:
                raise
            logger.error(
                "fusion_selection_source_missing", extra={"fusion_run_id": str(run.fusion_run_id)}
            )
            raise HTTPException(500, "Stored Fusion source result is missing") from error
        except (ValueError, TypeError, KeyError) as error:
            logger.error(
                "fusion_selection_reasons_invalid",
                extra={"fusion_run_id": str(run.fusion_run_id),
                       "validation_error_type": type(error).__name__},
            )
            raise HTTPException(
                500, "Stored Fusion selection reasons failed integrity validation"
            ) from error

    def explanations(self, run_id: UUID) -> FusionExplanations:
        rows = self.fetch(
            f"SELECT {_COLUMNS} FROM selection.fusion_run r WHERE r.fusion_run_id = %s",
            [run_id],
        )
        if not rows:
            raise HTTPException(404, "Fusion run not found")
        try:
            row = rows[0]
            run = _v1_run(row)
            version = run.provenance.get("explanation_schema_version")
            recorded = version in EXPLANATION_VERSIONS and run.status != "FAILED"
            if version is not None and version not in EXPLANATION_VERSIONS:
                raise ValueError("Unsupported stored explanation version")
            stored_candidates = row["candidates"]
            if not isinstance(stored_candidates, list):
                raise ValueError("Invalid stored explanation candidate list")
            raw = {str(candidate["instrument_id"]): candidate.get("explanation")
                   for candidate in stored_candidates}
            if recorded:
                config = run.provenance.get("explanation_config")
                if (
                    not isinstance(config, dict)
                    or _canonical_hash(config) != run.provenance.get("explanation_config_hash")
                    or explanation_output_hash(raw) != run.provenance.get("explanation_output_hash")
                ):
                    raise ValueError("Stored explanation provenance/hash mismatch")
            elif any(value is not None for value in raw.values()):
                raise ValueError("Unversioned or failed run contains explanation snapshots")
            candidates = []
            for candidate in run.candidates:
                explanation = None
                if recorded:
                    explanation = _EXPLANATION_ADAPTER.validate_python(
                        raw[str(candidate.instrument_id)]
                    )
                    validate_stored_explanation(
                        explanation, candidate.model_dump(mode="json"),
                        context_id=run.execution_context_id, target_session=run.price_session_date,
                        cutoff_at=run.cutoff_at, rrf_k=run.rrf_k,
                        quant_id=run.quant_selection_run_id, llm_id=run.llm_preselection_run_id,
                    )
                candidates.append(CandidateExplanationView(
                    instrument_id=candidate.instrument_id, issuer_id=candidate.issuer_id,
                    position=candidate.position, status="RECORDED" if recorded else "NOT_RECORDED",
                    explanation=explanation,
                ))
            return FusionExplanations(
                schema_version=EXTERNAL_SCHEMA_VERSION if version == EXTERNAL_SCHEMA_VERSION
                else SCHEMA_VERSION,
                fusion_run_id=run.fusion_run_id,
                execution_context_id=run.execution_context_id,
                price_session_date=run.price_session_date, cutoff_at=run.cutoff_at,
                selection_status=run.status, failure_code=run.failure_code,
                status="RECORDED" if recorded else "NOT_RECORDED", candidates=candidates,
            )
        except (ValueError, TypeError, KeyError, ValidationError) as error:
            logger.error(
                "fusion_explanation_snapshot_invalid",
                extra={"fusion_run_id": str(run_id), "validation_error_type": type(error).__name__},
            )
            raise HTTPException(
                500, "Stored Fusion explanation failed integrity validation"
            ) from error
