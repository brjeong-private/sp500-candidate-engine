from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from typing import LiteralString, Protocol


class ManifestLineageError(ValueError):
    """Raised when a manifest has an incomplete or ambiguous snapshot chain."""


class _Cursor(Protocol):
    def fetchall(self) -> list[dict[str, object]]: ...


class QueryConnection(Protocol):
    def execute(self, sql: LiteralString, params: tuple[object, ...], /) -> _Cursor: ...


@dataclass(frozen=True)
class ManifestSnapshot:
    source_snapshot_id: uuid.UUID
    dataset_code: str
    snapshot_kind: str
    lineage_role: str
    precedence: int
    parent_snapshot_id: uuid.UUID | None
    coverage_start: date | None = None
    coverage_end: date | None = None


def validate_manifest_lineage(snapshots: tuple[ManifestSnapshot, ...]) -> None:
    by_dataset: dict[str, list[ManifestSnapshot]] = defaultdict(list)
    for snapshot in snapshots:
        by_dataset[snapshot.dataset_code].append(snapshot)
    all_by_id = {snapshot.source_snapshot_id: snapshot for snapshot in snapshots}

    for dataset_code, members in by_dataset.items():
        precedence = [member.precedence for member in members]
        if len(precedence) != len(set(precedence)):
            raise ManifestLineageError(f"{dataset_code} has duplicate precedence")
        if any(value < 0 for value in precedence):
            raise ManifestLineageError(f"{dataset_code} has negative precedence")
        if all(member.lineage_role == "SINGLE" for member in members):
            if any(member.snapshot_kind != "FULL" for member in members):
                raise ManifestLineageError(
                    f"{dataset_code} SINGLE lineage must reference FULL snapshots"
                )
            continue
        if any(member.lineage_role == "SINGLE" for member in members):
            raise ManifestLineageError(
                f"{dataset_code} cannot mix SINGLE and chained lineage"
            )

        for member in members:
            if (
                member.lineage_role == "DELTA"
                and member.parent_snapshot_id not in all_by_id
            ):
                raise ManifestLineageError(
                    f"{dataset_code} delta has a missing parent: {member.parent_snapshot_id}"
                )
        baselines = [member for member in members if member.lineage_role == "BASELINE"]
        if len(baselines) > 1 or any(
            member.snapshot_kind != "FULL" for member in baselines
        ):
            raise ManifestLineageError(
                f"{dataset_code} can have at most one FULL baseline"
            )
        for member in members:
            if member.lineage_role == "BASELINE":
                if member.parent_snapshot_id is not None:
                    raise ManifestLineageError(
                        f"{dataset_code} baseline cannot have a parent"
                    )
                continue
            if member.lineage_role != "DELTA" or member.snapshot_kind != "DELTA":
                raise ManifestLineageError(
                    f"{dataset_code} non-baseline snapshots must be DELTA"
                )
            parent = all_by_id.get(member.parent_snapshot_id)
            if parent is None:
                raise ManifestLineageError(
                    f"{dataset_code} delta has a missing parent: {member.parent_snapshot_id}"
                )
            if (
                parent.dataset_code == member.dataset_code
                and parent.precedence >= member.precedence
            ):
                raise ManifestLineageError(
                    f"{dataset_code} delta precedence must follow its parent"
                )

        for member in members:
            seen: set[uuid.UUID] = set()
            current = member
            while current.snapshot_kind != "FULL":
                if current.source_snapshot_id in seen:
                    raise ManifestLineageError(f"{dataset_code} lineage contains a cycle")
                seen.add(current.source_snapshot_id)
                parent = all_by_id.get(current.parent_snapshot_id)
                if parent is None:
                    raise ManifestLineageError(
                        f"{dataset_code} delta has a missing parent"
                    )
                current = parent


class SourceRepository:
    def __init__(self, connection: QueryConnection) -> None:
        self.connection = connection

    def validate_context_manifest(self, *, execution_context_id: uuid.UUID) -> None:
        snapshots = self.connection.execute(
            """
            SELECT
                ss.source_snapshot_id, imm.dataset_code, ss.snapshot_kind,
                imm.lineage_role, imm.precedence, ss.parent_snapshot_id,
                ss.coverage_start, ss.coverage_end
            FROM ops.execution_context ec
            JOIN ops.input_manifest_member imm
              ON imm.input_manifest_id = ec.input_manifest_id
            JOIN ops.source_snapshot ss
              ON ss.source_snapshot_id = imm.source_snapshot_id
            WHERE ec.execution_context_id = %s
            ORDER BY imm.dataset_code, imm.precedence
            """,
            (execution_context_id,),
        ).fetchall()
        validate_manifest_lineage(
            tuple(
                ManifestSnapshot(
                    source_snapshot_id=row["source_snapshot_id"],  # type: ignore[arg-type]
                    dataset_code=str(row["dataset_code"]),
                    snapshot_kind=str(row["snapshot_kind"]),
                    lineage_role=str(row["lineage_role"]),
                    precedence=int(row["precedence"]),  # type: ignore[arg-type]
                    parent_snapshot_id=row["parent_snapshot_id"],  # type: ignore[arg-type]
                    coverage_start=row["coverage_start"],  # type: ignore[arg-type]
                    coverage_end=row["coverage_end"],  # type: ignore[arg-type]
                )
                for row in snapshots
            )
        )

    def read_bars(
        self,
        *,
        execution_context_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        self.validate_context_manifest(execution_context_id=execution_context_id)
        rows = self.connection.execute(
            """
            WITH manifest_bars AS (
                SELECT
                    bar.*,
                    obs.source_snapshot_id AS manifest_snapshot_id,
                    obs.observed_at AS manifest_observed_at,
                    imm.precedence,
                    row_number() OVER (
                        PARTITION BY bar.instrument_id, bar.session_date, bar.source_id
                        ORDER BY imm.precedence DESC, bar.revision_no DESC
                    ) AS selected_revision
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN market.daily_bar_observation obs
                  ON obs.source_snapshot_id = imm.source_snapshot_id
                JOIN market.daily_bar bar
                  ON bar.instrument_id = obs.instrument_id
                 AND bar.session_date = obs.session_date
                 AND bar.source_id = obs.source_id
                 AND bar.revision_no = obs.revision_no
                WHERE ec.execution_context_id = %s
                  AND bar.session_date BETWEEN %s AND %s
                  AND bar.source_available_at <= ec.cutoff_at
                  AND (
                      ec.knowledge_mode <> 'OPERATIONAL_REPLAY'
                      OR obs.observed_at <= ec.cutoff_at
                  )
            )
            SELECT
                instrument_id, session_date, source_id, revision_no,
                open, high, low, close, adjusted_close, volume, vwap,
                price_adjustment_status, volume_adjustment_status,
                manifest_snapshot_id AS source_snapshot_id, source_available_at,
                manifest_observed_at AS observed_at
            FROM manifest_bars
            WHERE selected_revision = 1
            ORDER BY instrument_id, session_date
            """,
            (execution_context_id, start_date, end_date),
        ).fetchall()
        return rows

    def read_context(
        self, *, execution_context_id: uuid.UUID
    ) -> dict[str, object]:
        rows = self.connection.execute(
            """
            SELECT execution_context_id, input_manifest_id, cutoff_at,
                knowledge_mode, code_version, config_version, context_hash
            FROM ops.execution_context
            WHERE execution_context_id = %s
            """,
            (execution_context_id,),
        ).fetchall()
        if len(rows) != 1:
            raise ValueError(f"Unknown execution context: {execution_context_id}")
        return rows[0]

    def read_universe_members(
        self,
        *,
        execution_context_id: uuid.UUID,
        target_session: date,
    ) -> list[dict[str, object]]:
        return self.connection.execute(
            """
            WITH eligible_versions AS (
                SELECT
                    uv.universe_version_id, uv.source_snapshot_id,
                    uv.as_of_date, uv.announced_at, uv.effective_at,
                    ss.source_available_at,
                    row_number() OVER (
                        ORDER BY uv.effective_at DESC, uv.as_of_date DESC,
                            uv.universe_version_id DESC
                    ) AS selected_version
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN ops.source_snapshot ss
                  ON ss.source_snapshot_id = imm.source_snapshot_id
                JOIN ref.universe_version uv
                  ON uv.source_snapshot_id = imm.source_snapshot_id
                WHERE ec.execution_context_id = %s
                  AND uv.as_of_date <= %s
                  AND uv.announced_at <= ec.cutoff_at
                  AND uv.effective_at <= ec.cutoff_at
                  AND ss.source_available_at <= ec.cutoff_at
                  AND (
                      ec.knowledge_mode <> 'OPERATIONAL_REPLAY'
                      OR ss.fetched_at <= ec.cutoff_at
                  )
            ), current_state AS (
                SELECT
                    state.*,
                    row_number() OVER (
                        PARTITION BY state.instrument_id
                        ORDER BY imm.precedence DESC, state.revision_no DESC
                    ) AS selected_state
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN ref.instrument_state state
                  ON state.source_snapshot_id = imm.source_snapshot_id
                WHERE ec.execution_context_id = %s
                  AND state.valid_from <= %s
                  AND (state.valid_to IS NULL OR state.valid_to >= %s)
                  AND state.source_available_at <= ec.cutoff_at
                  AND (
                      ec.knowledge_mode <> 'OPERATIONAL_REPLAY'
                      OR state.observed_at <= ec.cutoff_at
                  )
            )
            SELECT
                um.instrument_id, instrument.issuer_id, um.symbol,
                um.security_name, um.sector, um.sub_industry,
                state.primary_exchange, state.status AS instrument_status,
                version.universe_version_id,
                version.source_snapshot_id AS universe_snapshot_id,
                version.source_available_at AS universe_source_available_at,
                version.announced_at, version.effective_at,
                state.source_snapshot_id AS state_snapshot_id,
                state.instrument_state_id, state.source_available_at,
                state.observed_at
            FROM eligible_versions version
            JOIN ref.universe_member um
              ON um.universe_version_id = version.universe_version_id
            JOIN ref.instrument instrument
              ON instrument.instrument_id = um.instrument_id
            JOIN current_state state
              ON state.instrument_id = um.instrument_id
             AND state.selected_state = 1
            WHERE version.selected_version = 1
              AND state.status IN ('ACTIVE', 'LISTED')
            ORDER BY um.instrument_id
            """,
            (
                execution_context_id,
                target_session,
                execution_context_id,
                target_session,
                target_session,
            ),
        ).fetchall()

    def read_events(
        self,
        *,
        execution_context_id: uuid.UUID,
        instrument_id: uuid.UUID,
        event_type: str,
        start_at: datetime,
        end_at: datetime | None = None,
        clock: str = "EVENT",
    ) -> list[dict[str, object]]:
        clocks: dict[str, LiteralString] = {
            "EVENT": """COALESCE(
                      revision.published_at,
                      revision.scheduled_at,
                      revision.source_available_at
                  )""",
            "AVAILABLE": "revision.source_available_at",
            "SCHEDULE": "revision.scheduled_at",
        }
        if clock not in clocks:
            raise ValueError("Unknown event clock")
        upper_bound = "ec.cutoff_at" if end_at is None else "%s"
        return self.connection.execute(
            f"""
            WITH manifest_events AS (
                SELECT
                    event.event_id, event.event_type, event.source_event_id,
                    revision.event_revision_id, revision.revision_no,
                    revision.title, revision.status, revision.scheduled_at,
                    revision.published_at, revision.source_available_at,
                    revision.metadata,
                    obs.source_snapshot_id,
                    obs.observed_at AS manifest_observed_at,
                    imm.precedence,
                    row_number() OVER (
                        PARTITION BY event.event_id
                        ORDER BY imm.precedence DESC, revision.revision_no DESC
                    ) AS selected_revision
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN event.event_revision_observation obs
                  ON obs.source_snapshot_id = imm.source_snapshot_id
                JOIN event.event_revision revision
                  ON revision.event_revision_id = obs.event_revision_id
                JOIN event.market_event event
                  ON event.event_id = revision.event_id
                JOIN event.event_instrument mapping
                  ON mapping.event_id = event.event_id
                WHERE ec.execution_context_id = %s
                  AND mapping.instrument_id = %s
                  AND event.event_type = %s
                  AND revision.source_available_at <= ec.cutoff_at
                  AND {clocks[clock]} BETWEEN %s AND {upper_bound}
                  AND (
                      ec.knowledge_mode <> 'OPERATIONAL_REPLAY'
                      OR obs.observed_at <= ec.cutoff_at
                  )
            )
            SELECT
                event_id, event_revision_id, event_type, source_event_id,
                revision_no, title, status, scheduled_at, published_at,
                source_snapshot_id, source_available_at,
                manifest_observed_at AS observed_at, metadata
            FROM manifest_events
            WHERE selected_revision = 1
            ORDER BY COALESCE(published_at, scheduled_at, source_available_at) DESC,
                event_revision_id
            """,
            (execution_context_id, instrument_id, event_type, start_at)
            + (() if end_at is None else (end_at,)),
        ).fetchall()

    def read_blocking_issues(
        self, *, execution_context_id: uuid.UUID
    ) -> list[dict[str, object]]:
        return self.connection.execute(
            """
            SELECT DISTINCT issue.entity_key, issue.rule_code
            FROM ops.execution_context ec
            JOIN ops.input_manifest_member imm ON imm.input_manifest_id = ec.input_manifest_id
            JOIN ops.source_snapshot snapshot
              ON snapshot.source_snapshot_id = imm.source_snapshot_id
            JOIN ops.data_quality_issue issue
              ON issue.ingestion_run_id = snapshot.ingestion_run_id
            WHERE ec.execution_context_id = %s
              AND issue.severity = 'BLOCKING'
              AND issue.detected_at <= ec.cutoff_at
              AND (issue.resolved_at IS NULL OR issue.resolved_at > ec.cutoff_at)
            """,
            (execution_context_id,),
        ).fetchall()

    def read_sec_filings(
        self,
        *,
        execution_context_id: uuid.UUID,
        issuer_id: uuid.UUID,
        filed_on_or_after: date,
    ) -> list[dict[str, object]]:
        return self.connection.execute(
            """
            WITH manifest_filings AS (
                SELECT
                    filing.*, obs.source_snapshot_id AS obs_snapshot_id, ss.source_available_at,
                    obs.observed_at AS manifest_observed_at,
                    imm.precedence,
                    row_number() OVER (
                        PARTITION BY filing.issuer_id, filing.accession_no
                        ORDER BY imm.precedence DESC, obs.observed_at DESC
                    ) AS selected_revision
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN fundamental.sec_filing_observation obs
                  ON obs.source_snapshot_id = imm.source_snapshot_id
                JOIN fundamental.sec_filing filing
                  ON filing.filing_id = obs.filing_id
                JOIN ops.source_snapshot ss
                  ON ss.source_snapshot_id = obs.source_snapshot_id
                WHERE ec.execution_context_id = %s
                  AND filing.issuer_id = %s
                  AND filing.filed_date >= %s
                  AND filing.accepted_at <= ec.cutoff_at
                  AND ss.source_available_at <= ec.cutoff_at
                  AND (
                      ec.knowledge_mode <> 'OPERATIONAL_REPLAY'
                      OR obs.observed_at <= ec.cutoff_at
                  )
            )
            SELECT
                filing_id, accession_no, form_type, period_end, filed_date,
                accepted_at, is_amendment, obs_snapshot_id AS source_snapshot_id,
                source_available_at, manifest_observed_at AS observed_at
            FROM manifest_filings
            WHERE selected_revision = 1
            ORDER BY accepted_at DESC, filing_id
            """,
            (execution_context_id, issuer_id, filed_on_or_after),
        ).fetchall()

    def read_sec_facts(
        self,
        *,
        execution_context_id: uuid.UUID,
        issuer_id: uuid.UUID,
        period_end_on_or_before: date,
    ) -> list[dict[str, object]]:
        return self.connection.execute(
            """
            WITH manifest_facts AS (
                SELECT
                    fact.*, filing.accession_no, filing.accepted_at,
                    obs.source_snapshot_id AS obs_snapshot_id,
                    obs.observed_at AS manifest_observed_at,
                    imm.precedence,
                    row_number() OVER (
                        PARTITION BY fact.context_hash
                        ORDER BY imm.precedence DESC, obs.observed_at DESC
                    ) AS selected_revision
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN fundamental.fact_observation obs
                  ON obs.source_snapshot_id = imm.source_snapshot_id
                JOIN fundamental.fact fact ON fact.fact_id = obs.fact_id
                JOIN fundamental.sec_filing filing
                  ON filing.filing_id = fact.filing_id
                WHERE ec.execution_context_id = %s
                  AND fact.issuer_id = %s
                  AND fact.period_end <= %s
                  AND fact.source_available_at <= ec.cutoff_at
                  AND filing.accepted_at <= ec.cutoff_at
                  AND (
                      ec.knowledge_mode <> 'OPERATIONAL_REPLAY'
                      OR obs.observed_at <= ec.cutoff_at
                  )
            )
            SELECT
                fact_id, filing_id, accession_no, accepted_at, taxonomy,
                concept, unit, period_start, period_end, value_numeric,
                fiscal_year, fiscal_period, frame, context_hash,
                obs_snapshot_id AS source_snapshot_id, source_available_at,
                manifest_observed_at AS observed_at
            FROM manifest_facts
            WHERE selected_revision = 1
            ORDER BY period_end DESC, accepted_at DESC, concept, fact_id
            """,
            (execution_context_id, issuer_id, period_end_on_or_before),
        ).fetchall()

    def read_corporate_actions(
        self,
        *,
        execution_context_id: uuid.UUID,
        instrument_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
        return self.connection.execute(
            """
            WITH manifest_actions AS (
                SELECT
                    action.*,
                    obs.source_snapshot_id,
                    obs.observed_at AS manifest_observed_at,
                    imm.precedence,
                    row_number() OVER (
                        PARTITION BY action.source_id, action.source_action_id
                        ORDER BY imm.precedence DESC, action.revision_no DESC
                    ) AS selected_revision
                FROM ops.execution_context ec
                JOIN ops.input_manifest_member imm
                  ON imm.input_manifest_id = ec.input_manifest_id
                JOIN market.corporate_action_observation obs
                  ON obs.source_snapshot_id = imm.source_snapshot_id
                JOIN market.corporate_action action
                  ON action.action_id = obs.action_id
                WHERE ec.execution_context_id = %s
                  AND action.instrument_id = %s
                  AND action.effective_date BETWEEN %s AND %s
                  AND action.source_available_at <= ec.cutoff_at
                  AND (
                      ec.knowledge_mode <> 'OPERATIONAL_REPLAY'
                      OR obs.observed_at <= ec.cutoff_at
                  )
            )
            SELECT
                action_id, action_type, effective_date, cash_amount, currency,
                declaration_date, record_date, pay_date, split_from, split_to,
                source_snapshot_id, source_available_at,
                manifest_observed_at AS observed_at
            FROM manifest_actions
            WHERE selected_revision = 1
            ORDER BY effective_date, action_id
            """,
            (execution_context_id, instrument_id, start_date, end_date),
        ).fetchall()
