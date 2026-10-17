from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path

from psycopg import Connection

from sp500_candidate_engine import __version__
from sp500_candidate_engine.analytics.adjustments import (
    AdjustmentPolicy,
    RawDailyValue,
    adjust_daily_values,
)
from sp500_candidate_engine.analytics.calendar import build_exchange_calendar
from sp500_candidate_engine.analytics.db import execute_many
from sp500_candidate_engine.analytics.export_models import (
    InstrumentSpan,
    QlibDailyValue,
    QlibExportDataset,
)
from sp500_candidate_engine.analytics.export_repository import QlibExportRepository
from sp500_candidate_engine.analytics.qlib_exporter import (
    EXPORTER_VERSION,
    QlibBinaryExporter,
)
from sp500_candidate_engine.analytics.source_repository import (
    ManifestSnapshot,
    SourceRepository,
    validate_manifest_lineage,
)
from sp500_candidate_engine.database import Database, _canonical_hash, _stable_uuid
from sp500_candidate_engine.production_models import CorporateAction


@dataclass(frozen=True)
class HistoricalInputContext:
    execution_context_id: uuid.UUID
    universe_version_id: uuid.UUID
    cutoff_at: datetime


@dataclass(frozen=True)
class HistoricalExportSummary:
    export_run_id: uuid.UUID
    execution_context_id: uuid.UUID
    universe_version_id: uuid.UUID
    start_date: date
    end_date: date
    session_count: int
    instrument_count: int
    row_count: int
    benchmark_session_count: int
    artifact_uri: str
    artifact_hash: str


def _as_float(value: object | None) -> float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    return float(value)  # type: ignore[arg-type]


class HistoricalQlibExportService:
    DATASET_CODES = (
        "massive_grouped_daily",
        "massive_grouped_daily_backfill",
        "massive_splits",
        "massive_splits_backfill",
        "massive_splits_backfill_derived",
        "sp500_universe",
        "sp500_universe_backfill",
    )

    def __init__(self, database: Database) -> None:
        self.database = database

    def prepare_preselection_context(
        self,
        *,
        start_date: date,
        end_date: date,
        decision_cutoff: datetime,
    ) -> HistoricalInputContext:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        with self.database.connect() as connection, connection.transaction():
            context_id, universe_id, cutoff_at = self._create_context(
                connection,
                start_date=start_date,
                end_date=end_date,
                decision_cutoff=decision_cutoff,
                include_evidence=True,
            )
        return HistoricalInputContext(context_id, universe_id, cutoff_at)

    def export(
        self,
        *,
        start_date: date,
        end_date: date,
        output_root: Path,
        qlib_version: str,
        decision_cutoff: datetime | None = None,
        require_snapshot_available_by_cutoff: bool = False,
        input_context: HistoricalInputContext | None = None,
    ) -> HistoricalExportSummary:
        if start_date > end_date:
            raise ValueError("start_date must be on or before end_date")
        if require_snapshot_available_by_cutoff and decision_cutoff is None:
            raise ValueError(
                "decision_cutoff is required when snapshot availability is enforced"
            )
        with self.database.connect() as connection:
            if input_context is None:
                with connection.transaction():
                    context_id, universe_version_id, cutoff_at = self._create_context(
                        connection,
                        start_date=start_date,
                        end_date=end_date,
                        decision_cutoff=decision_cutoff,
                        require_snapshot_available_by_cutoff=(
                            require_snapshot_available_by_cutoff
                        ),
                    )
            else:
                source = SourceRepository(connection)
                context = source.read_context(
                    execution_context_id=input_context.execution_context_id
                )
                if (
                    decision_cutoff != input_context.cutoff_at
                    or context["cutoff_at"] != input_context.cutoff_at
                ):
                    raise ValueError("Prepared input context cutoff mismatch")
                source.validate_context_manifest(
                    execution_context_id=input_context.execution_context_id
                )
                if require_snapshot_available_by_cutoff:
                    raise ValueError(
                        "Prepared reconstruction context cannot certify snapshot availability"
                    )
                context_id = input_context.execution_context_id
                universe_version_id = input_context.universe_version_id
                cutoff_at = input_context.cutoff_at
            calendar = build_exchange_calendar(
                exchange_mic="XNYS",
                start_date=start_date,
                end_date=end_date,
            )
            bars = SourceRepository(connection).read_bars(
                execution_context_id=context_id,
                start_date=start_date,
                end_date=end_date,
            )
            actions = self._read_split_actions(
                connection,
                execution_context_id=context_id,
                end_date=end_date,
            )
            benchmark_count = self._benchmark_session_count(
                connection,
                execution_context_id=context_id,
                start_date=start_date,
                end_date=end_date,
            )
            dataset = self._build_dataset(
                context_id=context_id,
                universe_version_id=universe_version_id,
                cutoff_at=cutoff_at,
                calendar=tuple(session.session_date for session in calendar.sessions),
                bars=bars,
                actions=actions,
            )
            repository = QlibExportRepository(connection)
            export_run_id = repository.create_run(
                execution_context_id=context_id,
                universe_version_id=universe_version_id,
                start_date=start_date,
                end_date=end_date,
                adjustment_policy=AdjustmentPolicy.SPLIT_ONLY.value,
                qlib_version=qlib_version,
                exporter_version=EXPORTER_VERSION,
            )
            dataset = QlibExportDataset(
                export_run_id=export_run_id,
                execution_context_id=dataset.execution_context_id,
                universe_version_id=dataset.universe_version_id,
                cutoff_at=dataset.cutoff_at,
                adjustment_policy=dataset.adjustment_policy,
                calendar=dataset.calendar,
                instrument_spans=dataset.instrument_spans,
                daily_values=dataset.daily_values,
            )
            try:
                result = QlibBinaryExporter().export(
                    dataset=dataset,
                    output_root=output_root,
                )
                with connection.transaction():
                    repository.write_dataset(
                        dataset=dataset,
                        sessions=calendar.sessions,
                        membership_source="HISTORICAL_PRICE_SPAN",
                    )
                    repository.complete_run(
                        export_run_id=export_run_id,
                        artifact_uri=result.export_dir.resolve().as_uri(),
                        artifact_hash=result.content_hash,
                        row_count=result.row_count,
                    )
            except Exception as exc:
                with connection.transaction():
                    repository.fail_run(
                        export_run_id=export_run_id,
                        error_message=str(exc),
                    )
                raise
        return HistoricalExportSummary(
            export_run_id=export_run_id,
            execution_context_id=context_id,
            universe_version_id=universe_version_id,
            start_date=start_date,
            end_date=end_date,
            session_count=len(dataset.calendar),
            instrument_count=len(dataset.instrument_spans),
            row_count=result.row_count,
            benchmark_session_count=benchmark_count,
            artifact_uri=result.export_dir.resolve().as_uri(),
            artifact_hash=result.content_hash,
        )

    def _create_context(
        self,
        connection: Connection[dict[str, object]],
        *,
        start_date: date,
        end_date: date,
        decision_cutoff: datetime | None = None,
        require_snapshot_available_by_cutoff: bool = False,
        include_evidence: bool = False,
    ) -> tuple[uuid.UUID, uuid.UUID, datetime]:
        rows = connection.execute(
            """
            WITH ranked_contexts AS (
                SELECT
                    ir.target_date,
                    ec.input_manifest_id,
                    ec.cutoff_at,
                    row_number() OVER (
                        PARTITION BY ir.target_date
                        ORDER BY ec.created_at DESC
                    ) AS context_rank
                FROM ops.ingestion_run ir
                JOIN ops.source_snapshot price_snapshot
                  ON price_snapshot.ingestion_run_id = ir.ingestion_run_id
                 AND price_snapshot.dataset_code = ANY(%s::text[])
                JOIN ops.input_manifest_member price_member
                  ON price_member.source_snapshot_id = price_snapshot.source_snapshot_id
                JOIN ops.execution_context ec
                  ON ec.input_manifest_id = price_member.input_manifest_id
                WHERE ir.dataset_code = ANY(%s::text[])
                  AND ir.status = 'SUCCEEDED'
                  AND ir.target_date BETWEEN %s AND %s
                  AND (
                      %s::boolean = false
                      OR (
                          ec.cutoff_at <= %s
                          AND NOT EXISTS (
                              SELECT 1
                              FROM ops.input_manifest_member cutoff_member
                              JOIN ops.source_snapshot cutoff_snapshot
                                ON cutoff_snapshot.source_snapshot_id =
                                   cutoff_member.source_snapshot_id
                              WHERE cutoff_member.input_manifest_id =
                                    ec.input_manifest_id
                                AND cutoff_snapshot.source_available_at > %s
                          )
                      )
                  )
            )
            SELECT DISTINCT
                ss.source_snapshot_id, ss.dataset_code, ss.snapshot_kind,
                ss.parent_snapshot_id, ss.coverage_start, ss.coverage_end,
                rc.cutoff_at
            FROM ranked_contexts rc
            JOIN ops.input_manifest_member imm
              ON imm.input_manifest_id = rc.input_manifest_id
            JOIN ops.source_snapshot ss
              ON ss.source_snapshot_id = imm.source_snapshot_id
            WHERE rc.context_rank = 1
              AND (%s::boolean OR ss.dataset_code = ANY(%s::text[]))
              AND (
                  %s::boolean = false
                  OR ss.source_available_at <= %s
              )
            ORDER BY ss.dataset_code, ss.coverage_start, ss.source_snapshot_id
            """,
            (
                ["massive_grouped_daily_backfill", "massive_grouped_daily"],
                ["massive_price_backfill", "production_daily_input"],
                start_date,
                end_date,
                require_snapshot_available_by_cutoff,
                decision_cutoff,
                decision_cutoff,
                include_evidence,
                list(self.DATASET_CODES),
                require_snapshot_available_by_cutoff,
                decision_cutoff,
            ),
        ).fetchall()
        if not rows:
            raise RuntimeError("No historical reconstruction snapshots were found")
        if include_evidence:
            dependencies = connection.execute(
                """
                WITH evidence_dependencies AS (
                    SELECT state.source_snapshot_id
                    FROM ref.instrument_state state
                    WHERE state.valid_from <= %s
                      AND (state.valid_to IS NULL OR state.valid_to >= %s)
                      AND state.source_available_at <= %s
                    UNION
                    SELECT observation.source_snapshot_id
                    FROM fundamental.sec_filing_observation observation
                    JOIN fundamental.sec_filing filing USING (filing_id)
                    WHERE filing.accepted_at <= %s AND filing.filed_date <= %s
                    UNION
                    SELECT observation.source_snapshot_id
                    FROM fundamental.fact_observation observation
                    JOIN fundamental.fact fact USING (fact_id)
                    WHERE fact.source_available_at <= %s AND fact.period_end <= %s
                    UNION
                    SELECT observation.source_snapshot_id
                    FROM event.event_revision_observation observation
                    JOIN event.event_revision revision USING (event_revision_id)
                    WHERE revision.source_available_at <= %s
                    UNION
                    SELECT observation.source_snapshot_id
                    FROM market.corporate_action_observation observation
                    JOIN market.corporate_action action USING (action_id)
                    WHERE action.source_available_at <= %s
                )
                SELECT DISTINCT snapshot.source_snapshot_id, snapshot.dataset_code,
                    snapshot.snapshot_kind, snapshot.parent_snapshot_id,
                    snapshot.coverage_start, snapshot.coverage_end,
                    snapshot.source_available_at AS cutoff_at
                FROM evidence_dependencies dependency
                JOIN ops.source_snapshot snapshot USING (source_snapshot_id)
                WHERE snapshot.coverage_end <= %s
                  AND snapshot.source_available_at <= %s
                """,
                (
                    end_date, end_date, decision_cutoff, decision_cutoff, end_date,
                    decision_cutoff, end_date, decision_cutoff, decision_cutoff,
                    end_date, decision_cutoff,
                ),
            ).fetchall()
            rows.extend(dependencies)
        by_id = {row["source_snapshot_id"]: row for row in rows}
        missing_parent_ids = {
            row["parent_snapshot_id"]
            for row in rows
            if row["parent_snapshot_id"] is not None and row["parent_snapshot_id"] not in by_id
        }
        while missing_parent_ids:
            parents = connection.execute(
                """
                SELECT
                    source_snapshot_id, dataset_code, snapshot_kind,
                    parent_snapshot_id, coverage_start, coverage_end,
                    source_available_at AS cutoff_at
                FROM ops.source_snapshot
                WHERE source_snapshot_id = ANY(%s::uuid[])
                  AND (
                      %s::boolean = false
                      OR source_available_at <= %s
                  )
                """,
                (
                    list(missing_parent_ids),
                    require_snapshot_available_by_cutoff,
                    decision_cutoff,
                ),
            ).fetchall()
            if len(parents) != len(missing_parent_ids):
                raise RuntimeError("Historical snapshot parent lineage is incomplete")
            for parent in parents:
                by_id[parent["source_snapshot_id"]] = parent
            missing_parent_ids = {
                row["parent_snapshot_id"]
                for row in parents
                if row["parent_snapshot_id"] is not None and row["parent_snapshot_id"] not in by_id
            }

        snapshots = list(by_id.values())
        precedence_by_dataset: dict[str, int] = defaultdict(int)
        manifest_snapshots: list[ManifestSnapshot] = []
        member_rows: list[tuple[uuid.UUID, str, int, str]] = []
        for row in sorted(
            snapshots,
            key=lambda item: (
                str(item["dataset_code"]),
                item["coverage_start"],  # type: ignore[arg-type]
                str(item["source_snapshot_id"]),
            ),
        ):
            dataset_code = str(row["dataset_code"])
            precedence = precedence_by_dataset[dataset_code]
            precedence_by_dataset[dataset_code] += 1
            snapshot_kind = str(row["snapshot_kind"])
            role = "DELTA" if snapshot_kind == "DELTA" else "SINGLE"
            snapshot_id = uuid.UUID(str(row["source_snapshot_id"]))
            parent_id = (
                uuid.UUID(str(row["parent_snapshot_id"]))
                if row["parent_snapshot_id"] is not None
                else None
            )
            manifest_snapshots.append(
                ManifestSnapshot(
                    source_snapshot_id=snapshot_id,
                    dataset_code=dataset_code,
                    snapshot_kind=snapshot_kind,
                    lineage_role=role,
                    precedence=precedence,
                    parent_snapshot_id=parent_id,
                    coverage_start=row["coverage_start"],  # type: ignore[arg-type]
                    coverage_end=row["coverage_end"],  # type: ignore[arg-type]
                )
            )
            member_rows.append((snapshot_id, dataset_code, precedence, role))
        validate_manifest_lineage(tuple(manifest_snapshots))

        manifest_payload = [
            {
                "source_snapshot_id": snapshot_id,
                "dataset_code": dataset_code,
                "precedence": precedence,
                "lineage_role": role,
            }
            for snapshot_id, dataset_code, precedence, role in member_rows
        ]
        manifest_hash = _canonical_hash(manifest_payload)
        manifest_id = _stable_uuid("historical-qlib-manifest", manifest_hash)
        connection.execute(
            """
            INSERT INTO ops.input_manifest(input_manifest_id, manifest_hash)
            VALUES (%s, %s)
            ON CONFLICT (manifest_hash) DO NOTHING
            """,
            (manifest_id, manifest_hash),
        )
        execute_many(
            connection,
            """
            INSERT INTO ops.input_manifest_member(
                input_manifest_id, source_snapshot_id,
                dataset_code, precedence, lineage_role
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            [
                (manifest_id, snapshot_id, dataset_code, precedence, role)
                for snapshot_id, dataset_code, precedence, role in member_rows
            ],
        )
        cutoff_at = (
            decision_cutoff
            if decision_cutoff is not None
            else max(row["cutoff_at"] for row in rows)  # type: ignore[type-var]
        )
        context_config_version = (
            "historical-preselection-context-v2" if include_evidence
            else "historical-qlib-export-v1"
        )
        context_hash = _canonical_hash(
            {
                "input_manifest_id": manifest_id,
                "cutoff_at": cutoff_at,
                "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
                "code_version": __version__,
                "config_version": context_config_version,
            }
        )
        context_id = _stable_uuid("historical-qlib-context", context_hash)
        connection.execute(
            """
            INSERT INTO ops.execution_context(
                execution_context_id, input_manifest_id, cutoff_at,
                knowledge_mode, code_version, config_version, context_hash
            )
            VALUES (%s, %s, %s, 'HISTORICAL_RECONSTRUCTION', %s, %s, %s)
            ON CONFLICT (context_hash) DO NOTHING
            """,
            (
                context_id,
                manifest_id,
                cutoff_at,
                __version__,
                context_config_version,
                context_hash,
            ),
        )
        universe = connection.execute(
            """
            SELECT uv.universe_version_id
            FROM ref.universe_version uv
            JOIN ops.source_snapshot ss
              ON ss.source_snapshot_id = uv.source_snapshot_id
            WHERE ss.source_snapshot_id = ANY(%s::uuid[])
              AND uv.as_of_date <= %s
            ORDER BY uv.as_of_date DESC, uv.created_at DESC
            LIMIT 1
            """,
            ([row[0] for row in member_rows], end_date),
        ).fetchone()
        if universe is None:
            raise RuntimeError("No universe version exists in the export manifest")
        return (
            context_id,
            uuid.UUID(str(universe["universe_version_id"])),
            cutoff_at,  # type: ignore[return-value]
        )

    @staticmethod
    def _read_split_actions(
        connection: Connection[dict[str, object]],
        *,
        execution_context_id: uuid.UUID,
        end_date: date,
    ) -> dict[uuid.UUID, tuple[CorporateAction, ...]]:
        rows = connection.execute(
            """
            WITH ranked_actions AS (
                SELECT
                    action.*,
                    row_number() OVER (
                        PARTITION BY action.source_id, action.source_action_id
                        ORDER BY action.revision_no DESC, imm.precedence DESC
                    ) AS selected_revision
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN market.corporate_action_observation observation
                  ON observation.source_snapshot_id = imm.source_snapshot_id
                JOIN market.corporate_action action
                  ON action.action_id = observation.action_id
                WHERE ec.execution_context_id = %s
                  AND action.action_type = 'SPLIT'
                  AND action.effective_date <= %s
                  AND action.source_available_at <= ec.cutoff_at
            )
            SELECT * FROM ranked_actions
            WHERE selected_revision = 1
            ORDER BY instrument_id, effective_date, source_action_id
            """,
            (execution_context_id, end_date),
        ).fetchall()
        actions: dict[uuid.UUID, list[CorporateAction]] = defaultdict(list)
        for row in rows:
            instrument_id = uuid.UUID(str(row["instrument_id"]))
            actions[instrument_id].append(
                CorporateAction(
                    provider_action_id=str(row["source_action_id"]),
                    symbol=f"I{instrument_id.hex.upper()}",
                    action_type="SPLIT",
                    effective_date=row["effective_date"],  # type: ignore[arg-type]
                    declaration_date=row["declaration_date"],  # type: ignore[arg-type]
                    record_date=row["record_date"],  # type: ignore[arg-type]
                    pay_date=row["pay_date"],  # type: ignore[arg-type]
                    cash_amount=_as_float(row["cash_amount"]),
                    currency=str(row["currency"]) if row["currency"] else None,
                    split_from=_as_float(row["split_from"]),
                    split_to=_as_float(row["split_to"]),
                    source_available_at=row["source_available_at"],  # type: ignore[arg-type]
                    metadata=row["metadata"],  # type: ignore[arg-type]
                )
            )
        return {key: tuple(value) for key, value in actions.items()}

    @staticmethod
    def _benchmark_session_count(
        connection: Connection[dict[str, object]],
        *,
        execution_context_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> int:
        row = connection.execute(
            """
            SELECT count(DISTINCT benchmark.session_date) AS session_count
            FROM ops.execution_context ec
            JOIN ops.input_manifest_member imm
              ON imm.input_manifest_id = ec.input_manifest_id
            JOIN market.benchmark_daily_bar benchmark
              ON benchmark.source_snapshot_id = imm.source_snapshot_id
            WHERE ec.execution_context_id = %s
              AND benchmark.benchmark_code = 'SPY'
              AND benchmark.session_date BETWEEN %s AND %s
              AND benchmark.source_available_at <= ec.cutoff_at
            """,
            (execution_context_id, start_date, end_date),
        ).fetchone()
        return int(row["session_count"]) if row else 0

    @staticmethod
    def _build_dataset(
        *,
        context_id: uuid.UUID,
        universe_version_id: uuid.UUID,
        cutoff_at: datetime,
        calendar: tuple[date, ...],
        bars: list[dict[str, object]],
        actions: dict[uuid.UUID, tuple[CorporateAction, ...]],
    ) -> QlibExportDataset:
        bars_by_instrument: dict[uuid.UUID, list[RawDailyValue]] = defaultdict(list)
        for row in bars:
            instrument_id = uuid.UUID(str(row["instrument_id"]))
            bars_by_instrument[instrument_id].append(
                RawDailyValue(
                    session_date=row["session_date"],  # type: ignore[arg-type]
                    open=float(row["open"]),  # type: ignore[arg-type]
                    high=float(row["high"]),  # type: ignore[arg-type]
                    low=float(row["low"]),  # type: ignore[arg-type]
                    close=float(row["close"]),  # type: ignore[arg-type]
                    volume=int(row["volume"]),  # type: ignore[arg-type]
                    vwap=_as_float(row["vwap"]),
                )
            )

        spans: list[InstrumentSpan] = []
        daily_values: list[QlibDailyValue] = []
        for instrument_id, instrument_bars in sorted(
            bars_by_instrument.items(),
            key=lambda item: item[0].hex,
        ):
            adjusted = adjust_daily_values(
                bars=tuple(sorted(instrument_bars, key=lambda item: item.session_date)),
                actions=actions.get(instrument_id, ()),
                calendar=calendar,
                policy=AdjustmentPolicy.SPLIT_ONLY,
            )
            symbol = f"I{instrument_id.hex.upper()}"
            spans.append(
                InstrumentSpan(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    start_date=adjusted[0].session_date,
                    end_date=adjusted[-1].session_date,
                )
            )
            daily_values.extend(
                QlibDailyValue(
                    instrument_id=instrument_id,
                    symbol=symbol,
                    session_date=value.session_date,
                    open=value.open,
                    high=value.high,
                    low=value.low,
                    close=value.close,
                    volume=value.volume,
                    vwap=value.vwap,
                    factor=value.factor,
                    change=value.change,
                    quality_status=value.quality_status,
                )
                for value in adjusted
            )
        if not daily_values:
            raise RuntimeError("Historical export produced no daily values")
        return QlibExportDataset(
            export_run_id=uuid.UUID(int=0),
            execution_context_id=context_id,
            universe_version_id=universe_version_id,
            cutoff_at=cutoff_at,
            adjustment_policy=AdjustmentPolicy.SPLIT_ONLY.value,
            calendar=calendar,
            instrument_spans=tuple(spans),
            daily_values=tuple(daily_values),
        )
