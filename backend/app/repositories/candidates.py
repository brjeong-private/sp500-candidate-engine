from __future__ import annotations

from datetime import date, datetime
from uuid import UUID

from fastapi import HTTPException

from backend.app.pagination import date_filters, decode_cursor, encode_cursor, page_limit
from backend.app.repositories.base import ReadRepository
from backend.app.schemas.candidates import Candidate
from backend.app.schemas.common import Page


class CandidateRepository(ReadRepository):
    def list_candidates(
        self,
        *,
        exact_date: date | None = None,
        start_date: date | None = None,
        end_date: date | None = None,
        selection_run_id: UUID | None = None,
        model_purpose: str = "MEDIUM_20D",
        include_deleted: bool = False,
        ticker: str | None = None,
        instrument_id: UUID | None = None,
        issuer_id: UUID | None = None,
        cursor: str | None = None,
        limit: int = 100,
    ) -> Page[Candidate]:
        page_limit(limit)
        start_date, end_date = date_filters(exact_date, start_date, end_date)
        filters: dict[str, object] = {
            "start": start_date,
            "end": end_date,
            "run": selection_run_id,
            "model_purpose": model_purpose,
            "ticker": ticker,
            "instrument": instrument_id,
            "issuer": issuer_id,
        }
        position = decode_cursor(cursor, "candidates", filters, 4)
        anchor: datetime | None = None
        conditions = []
        parameters: list[object] = []
        if position is not None:
            try:
                anchor = datetime.fromisoformat(position[0])
                boundary_date = date.fromisoformat(position[1])
                boundary_position = int(position[2])
                boundary_instrument = UUID(position[3])
                if anchor.tzinfo is None:
                    raise ValueError
            except ValueError:
                raise HTTPException(422, "Invalid candidate cursor") from None
        parameters.append(anchor)
        run_conditions = ["s.created_at <= boundary.anchor"]
        if not include_deleted:
            run_conditions.append(
                "NOT EXISTS (SELECT 1 FROM selection.quant_result_deletion deletion "
                "WHERE deletion.selection_run_id = s.selection_run_id)"
            )
        if selection_run_id is None:
            run_conditions.append("s.status = 'SUCCEEDED'")
            run_conditions.append("m.model_purpose = %s")
            parameters.append(model_purpose)
        else:
            run_conditions.append("s.selection_run_id = %s")
            parameters.append(selection_run_id)
        if start_date is not None:
            run_conditions.append("s.price_session_date BETWEEN %s AND %s")
            parameters.extend([start_date, end_date])
        for column, value in (
            ("um.symbol", ticker),
            ("c.instrument_id", instrument_id),
            ("i.issuer_id", issuer_id),
        ):
            if value is not None:
                conditions.append(f"{column} = %s")
                parameters.append(value)
        if position is not None:
            conditions.append(
                "(s.price_session_date < %s OR (s.price_session_date = %s "
                "AND (c.position, c.instrument_id) > (%s, %s)))"
            )
            parameters.extend(
                [boundary_date, boundary_date, boundary_position, boundary_instrument]
            )
        parameters.append(limit + 1)
        query = f"""
            WITH boundary AS (
                SELECT COALESCE(%s::timestamptz, CURRENT_TIMESTAMP) AS anchor
            ), ranked AS (
                SELECT s.*, boundary.anchor AS _anchor,
                    m.model_purpose, m.return_policy, m.promotion_status,
                    m.model_name, m.version AS model_version,
                    ROW_NUMBER() OVER (
                        PARTITION BY s.price_session_date, m.model_purpose
                        ORDER BY s.generated_at DESC, s.created_at DESC, s.selection_run_id DESC
                    ) AS run_rank
                FROM selection.selection_run s
                JOIN analytics.scoring_run scoring
                    ON scoring.scoring_run_id = s.scoring_run_id
                JOIN analytics.model_version m
                    ON m.model_version_id = scoring.model_version_id
                CROSS JOIN boundary
                WHERE {" AND ".join(run_conditions)}
            )
            SELECT s.selection_run_id, s.selection_type, s.price_session_date,
                s.cutoff_at, s.generated_at, s.valid_until, s.scoring_run_id,
                s.policy_version, s.status, s.selected_count, s.requested_count,
                sc.model_version_id, sc.score_semantics, s.model_name,
                s.model_version, s.model_purpose, s.return_policy,
                s.promotion_status,
                ds.prediction_horizon AS prediction_horizon_sessions,
                c.instrument_id, i.issuer_id,
                um.symbol AS ticker, um.security_name AS company_name, um.sector,
                c.position, c.score, c.predicted_return, c.rank_overall,
                c.score_percentile, c.rank_sector, c.quality_status, c.latest_data_at,
                COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'reason_code', r.reason_code, 'priority', r.priority,
                        'event_revision_id', r.event_revision_id
                    ) ORDER BY r.priority, r.candidate_reason_id)
                    FROM selection.candidate_reason r
                    WHERE r.selection_run_id = c.selection_run_id
                      AND r.instrument_id = c.instrument_id
                ), '[]'::jsonb) AS reasons, s._anchor
            FROM ranked s
            JOIN selection.candidate c USING (selection_run_id)
            JOIN analytics.scoring_run sc ON sc.scoring_run_id = s.scoring_run_id
            JOIN analytics.daily_score ds
                ON ds.scoring_run_id = s.scoring_run_id
               AND ds.instrument_id = c.instrument_id
            JOIN ref.instrument i ON i.instrument_id = c.instrument_id
            JOIN ref.universe_member um ON um.universe_version_id = sc.universe_version_id
                AND um.instrument_id = c.instrument_id
            WHERE s.run_rank = 1 {"AND " + " AND ".join(conditions) if conditions else ""}
            ORDER BY s.price_session_date DESC, c.position ASC, c.instrument_id ASC
            LIMIT %s
        """
        rows = self.fetch(query, parameters)
        next_cursor = None
        if len(rows) > limit:
            last = rows[limit - 1]
            next_cursor = encode_cursor(
                "candidates",
                filters,
                [
                    str(last["_anchor"]),
                    str(last["price_session_date"]),
                    str(last["position"]),
                    str(last["instrument_id"]),
                ],
            )
        items = []
        for row in rows[:limit]:
            row.pop("_anchor")
            items.append(Candidate.model_validate(row))
        return Page[Candidate](items=items, next_cursor=next_cursor)
