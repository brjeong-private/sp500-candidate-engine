from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date
from typing import Protocol


class ManifestLineageError(ValueError):
    """Raised when a manifest has an incomplete or ambiguous snapshot chain."""


class _Cursor(Protocol):
    def fetchall(self) -> list[dict[str, object]]: ...


class QueryConnection(Protocol):
    def execute(self, sql: str, params: tuple[object, ...]) -> _Cursor: ...


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

    def read_bars(
        self,
        *,
        execution_context_id: uuid.UUID,
        start_date: date,
        end_date: date,
    ) -> list[dict[str, object]]:
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
        rows = self.connection.execute(
            """
            WITH manifest_bars AS (
                SELECT
                    bar.*,
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
                source_available_at, manifest_observed_at AS observed_at
            FROM manifest_bars
            WHERE selected_revision = 1
            ORDER BY instrument_id, session_date
            """,
            (execution_context_id, start_date, end_date),
        ).fetchall()
        return rows

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
                source_available_at, manifest_observed_at AS observed_at
            FROM manifest_facts
            WHERE selected_revision = 1
            ORDER BY period_end, accepted_at, concept
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
                split_from, split_to, source_available_at,
                manifest_observed_at AS observed_at
            FROM manifest_actions
            WHERE selected_revision = 1
            ORDER BY effective_date, action_id
            """,
            (execution_context_id, instrument_id, start_date, end_date),
        ).fetchall()
