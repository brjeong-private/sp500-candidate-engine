from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException

from backend.app.pagination import date_filters, decode_cursor, encode_cursor, page_limit
from backend.app.repositories.base import ReadRepository
from backend.app.schemas.common import Page
from backend.app.schemas.llm_preselections import LLMPreselection


class LLMPreselectionRepository(ReadRepository):
    _COLUMNS = """
            r.run_id, r.llm_ranking_run_id, ranking.execution_context_id,
            r.price_session_date, r.cutoff_at, r.generated_at, r.valid_until,
            r.policy_version, ranking.prompt_version, ranking.deployment,
            ranking.evidence_schema_version, r.requested_count, r.selected_count,
            r.status, ranking.status AS ranking_status, r.failure_code, r.created_at,
            COALESCE((
                SELECT jsonb_agg(jsonb_build_object(
                    'run_id', c.run_id,
                    'instrument_id', c.instrument_id,
                    'position', c.position,
                    'score', c.score,
                    'first_stage_rank', c.first_stage_rank,
                    'final_rank', c.final_rank,
                    'evidence_quality', c.evidence_quality,
                    'reason_codes', c.reason_codes,
                    'symbol', c.symbol,
                    'company_name', c.company_name,
                    'sector', c.sector,
                    'evidence', COALESCE((
                        SELECT jsonb_agg(jsonb_build_object(
                            'evidence_link_id', link.evidence_link_id,
                            'source_snapshot_id', link.source_snapshot_id,
                            'source_kind', link.source_kind,
                            'entity_key', link.entity_key,
                            'source_available_at', link.source_available_at,
                            'observed_at', link.observed_at,
                            'event_at', link.event_at,
                            'priority', selected_evidence.priority
                        ) ORDER BY selected_evidence.priority)
                        FROM selection.llm_preselection_evidence selected_evidence
                        JOIN analytics.llm_evidence_link link
                          ON link.evidence_link_id = selected_evidence.evidence_link_id
                        WHERE selected_evidence.run_id = c.run_id
                          AND selected_evidence.instrument_id = c.instrument_id
                    ), '[]'::jsonb)
                ) ORDER BY c.position, c.instrument_id)
                FROM selection.llm_preselection_candidate c
                WHERE c.run_id = r.run_id
            ), '[]'::jsonb) AS candidates
    """

    def list_preselections(
        self,
        *,
        exact_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        run_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[LLMPreselection]:
        page_limit(limit)
        start_date, end_date = date_filters(exact_date, start_date, end_date)
        filters: dict[str, object] = {
            "start": start_date,
            "end": end_date,
            "run": run_id,
        }
        position = decode_cursor(cursor, "llm-preselections", filters, 5)
        anchor: datetime | None = None
        conditions = ["r.created_at <= boundary.anchor"]
        parameters: list[object] = []
        boundary_values: tuple[date, datetime, datetime, UUID] | None = None
        if position is not None:
            try:
                anchor = datetime.fromisoformat(position[0])
                boundary_values = (
                    date.fromisoformat(position[1]),
                    datetime.fromisoformat(position[2]),
                    datetime.fromisoformat(position[3]),
                    UUID(position[4]),
                )
                if (
                    anchor.tzinfo is None
                    or boundary_values[1].tzinfo is None
                    or boundary_values[2].tzinfo is None
                ):
                    raise ValueError
            except ValueError:
                raise HTTPException(422, "Invalid LLM preselection cursor") from None
        parameters.append(anchor)
        if run_id is None:
            conditions.append("r.status = 'SUCCEEDED'")
        else:
            conditions.append("r.run_id = %s")
            parameters.append(run_id)
        if start_date is not None:
            conditions.append("r.price_session_date BETWEEN %s AND %s")
            parameters.extend([start_date, end_date])
        page_condition = ""
        if boundary_values is not None:
            page_condition = (
                "WHERE (r.price_session_date, r.generated_at, r.created_at, r.run_id) "
                "< (%s, %s, %s, %s)"
            )
            parameters.extend(boundary_values)
        parameters.append(limit + 1)
        query = f"""
            WITH boundary AS (
                SELECT COALESCE(%s::timestamptz, CURRENT_TIMESTAMP) AS anchor
            ), ranked AS (
                SELECT r.*, boundary.anchor AS _anchor,
                    ROW_NUMBER() OVER (
                        PARTITION BY r.price_session_date
                        ORDER BY r.generated_at DESC, r.created_at DESC, r.run_id DESC
                    ) AS run_rank
                FROM selection.llm_preselection_run r
                CROSS JOIN boundary
                WHERE {" AND ".join(conditions)}
            ), selected_runs AS (
                SELECT * FROM ranked r
                WHERE r.run_rank = 1
            )
            SELECT {self._COLUMNS}, r._anchor
            FROM selected_runs r
            JOIN analytics.llm_ranking_run ranking
                ON ranking.llm_ranking_run_id = r.llm_ranking_run_id
            {page_condition}
            ORDER BY r.price_session_date DESC, r.generated_at DESC,
                r.created_at DESC, r.run_id DESC
            LIMIT %s
        """
        rows = self.fetch(query, parameters)
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(
                "llm-preselections",
                filters,
                [
                    str(last["_anchor"]),
                    str(last["price_session_date"]),
                    str(last["generated_at"]),
                    str(last["created_at"]),
                    str(last["run_id"]),
                ],
            )
        items = []
        for row in rows[:limit]:
            row.pop("_anchor")
            items.append(LLMPreselection.model_validate(row))
        return Page[LLMPreselection](items=items, next_cursor=next_cursor)

    def get_preselection(self, run_id: UUID) -> LLMPreselection:
        query = f"""
            WITH selected_runs AS (
                SELECT *
                FROM selection.llm_preselection_run
                WHERE run_id = %s
            )
            SELECT {self._COLUMNS}
            FROM selected_runs r
            JOIN analytics.llm_ranking_run ranking
                ON ranking.llm_ranking_run_id = r.llm_ranking_run_id
        """
        rows = self.fetch(query, [run_id])
        if not rows:
            raise HTTPException(404, "LLM preselection run not found")
        row = rows[0]
        row.pop("_anchor", None)
        return LLMPreselection.model_validate(row)
