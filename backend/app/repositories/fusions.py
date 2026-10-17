from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException

from backend.app.pagination import date_filters, decode_cursor, encode_cursor, page_limit
from backend.app.repositories.base import ReadRepository
from backend.app.schemas.common import Page
from backend.app.schemas.fusions import FusionRun
from sp500_candidate_engine.database import _canonical_hash

_COLUMNS = """
    r.fusion_run_id, r.execution_context_id, r.quant_selection_run_id, r.llm_preselection_run_id,
    r.price_session_date, r.cutoff_at, r.generated_at, r.model_purpose, r.selection_type,
    r.policy_version, r.config_hash, r.rrf_k, r.requested_count, r.selected_count,
    r.union_count, r.status, r.failure_code, r.sector_cap_relaxed, r.provenance,
    r.payload_hash, r.created_at,
    COALESCE((SELECT jsonb_agg(candidate.candidate ORDER BY candidate.position)
              FROM selection.fusion_candidate candidate
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
        return FusionRun.model_validate(rows[0])

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
            items.append(FusionRun.model_validate(row))
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
            "candidates": data["candidates"],
        }
        envelope["payload_hash"] = _canonical_hash(envelope)
        return envelope
