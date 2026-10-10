from __future__ import annotations

import uuid
from datetime import date

from sp500_candidate_engine.analytics.calendar import ExchangeSession
from sp500_candidate_engine.analytics.db import execute_many
from sp500_candidate_engine.analytics.export_models import QlibExportDataset
from sp500_candidate_engine.database import _canonical_hash, _stable_uuid


def build_export_idempotency_key(
    *,
    execution_context_id: uuid.UUID,
    universe_version_id: uuid.UUID,
    start_date: date | str,
    end_date: date | str,
    adjustment_policy: str,
    exporter_version: str,
) -> str:
    return _canonical_hash(
        {
            "execution_context_id": execution_context_id,
            "universe_version_id": universe_version_id,
            "start_date": start_date,
            "end_date": end_date,
            "adjustment_policy": adjustment_policy,
            "exporter_version": exporter_version,
        }
    )


class QlibExportRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def create_run(
        self,
        *,
        execution_context_id: uuid.UUID,
        universe_version_id: uuid.UUID,
        start_date: date,
        end_date: date,
        adjustment_policy: str,
        qlib_version: str,
        exporter_version: str,
    ) -> uuid.UUID:
        idempotency_key = build_export_idempotency_key(
            execution_context_id=execution_context_id,
            universe_version_id=universe_version_id,
            start_date=start_date,
            end_date=end_date,
            adjustment_policy=adjustment_policy,
            exporter_version=exporter_version,
        )
        export_run_id = _stable_uuid("qlib-export-run", idempotency_key)
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.qlib_export_run(
                export_run_id, execution_context_id, universe_version_id,
                start_date, end_date, adjustment_policy, qlib_version,
                exporter_version, status, idempotency_key
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'RUNNING', %s)
            ON CONFLICT (idempotency_key) DO NOTHING
            """,
            (
                export_run_id,
                execution_context_id,
                universe_version_id,
                start_date,
                end_date,
                adjustment_policy,
                qlib_version,
                exporter_version,
                idempotency_key,
            ),
        )
        return export_run_id

    def complete_run(
        self,
        *,
        export_run_id: uuid.UUID,
        artifact_uri: str,
        artifact_hash: str,
        row_count: int,
    ) -> None:
        self.connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE analytics.qlib_export_run
               SET status = 'SUCCEEDED',
                   artifact_uri = %s,
                   artifact_hash = %s,
                   row_count = %s,
                   finished_at = now(),
                   error_message = NULL
             WHERE export_run_id = %s
               AND status IN ('RUNNING', 'SUCCEEDED')
            """,
            (artifact_uri, artifact_hash, row_count, export_run_id),
        )

    def write_dataset(
        self,
        *,
        dataset: QlibExportDataset,
        sessions: tuple[ExchangeSession, ...],
        membership_source: str,
    ) -> None:
        if tuple(session.session_date for session in sessions) != dataset.calendar:
            raise ValueError("Session metadata does not match the export calendar")
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO analytics.qlib_calendar(
                export_run_id, session_date, open_at, close_at, is_early_close
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    dataset.export_run_id,
                    session.session_date,
                    session.open_at,
                    session.close_at,
                    session.is_early_close,
                )
                for session in sessions
            ],
        )
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO analytics.qlib_instrument_span(
                export_run_id, instrument_id, symbol,
                start_date, end_date, membership_source
            )
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    dataset.export_run_id,
                    span.instrument_id,
                    span.symbol,
                    span.start_date,
                    span.end_date,
                    membership_source,
                )
                for span in dataset.instrument_spans
            ],
        )
        execute_many(
            self.connection,  # type: ignore[arg-type]
            """
            INSERT INTO analytics.qlib_daily_value(
                export_run_id, instrument_id, session_date,
                open, high, low, close, volume, vwap,
                factor, change, quality_status
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (
                    dataset.export_run_id,
                    value.instrument_id,
                    value.session_date,
                    value.open,
                    value.high,
                    value.low,
                    value.close,
                    value.volume,
                    value.vwap,
                    value.factor,
                    value.change,
                    value.quality_status,
                )
                for value in dataset.daily_values
            ],
        )

    def fail_run(self, *, export_run_id: uuid.UUID, error_message: str) -> None:
        self.connection.execute(  # type: ignore[attr-defined]
            """
            UPDATE analytics.qlib_export_run
               SET status = 'FAILED',
                   error_message = %s,
                   finished_at = now()
             WHERE export_run_id = %s
            """,
            (error_message, export_run_id),
        )
