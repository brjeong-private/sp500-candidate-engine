"""Freeze explicitly reviewed existing snapshots; never collect or select the newest context."""

from __future__ import annotations

import argparse
import json
import uuid
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

from sp500_candidate_engine import __version__
from sp500_candidate_engine.analytics.historical_safety import HistoricalSafetyError
from sp500_candidate_engine.analytics.historical_training import (
    CONTRACT_VERSION,
    ReconstructionRequest,
    _validate_sources,
)
from sp500_candidate_engine.analytics.source_repository import (
    ManifestSnapshot,
    validate_manifest_lineage,
)
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database, _canonical_hash, _stable_uuid


def freeze_training_context(
    *,
    database: Database,
    reconstruction_id: uuid.UUID,
    signal_session: date,
    anchor_session: date,
    training_cutoff: datetime,
    universe_version_id: uuid.UUID,
    members: tuple[ManifestSnapshot, ...],
) -> ReconstructionRequest:
    """One transaction: validate explicit lineage and freeze existing source observations."""
    if not members or len({member.source_snapshot_id for member in members}) != len(members):
        raise HistoricalSafetyError("explicit, nonempty, unique manifest members are required")
    validate_manifest_lineage(members)
    ordered = sorted(members, key=lambda member: (member.dataset_code, member.precedence))
    payload = [
        {
            "source_snapshot_id": member.source_snapshot_id,
            "dataset_code": member.dataset_code,
            "precedence": member.precedence,
            "lineage_role": member.lineage_role,
        }
        for member in ordered
    ]
    manifest_hash = _canonical_hash(payload)
    manifest_id = _stable_uuid("historical-qlib-manifest", manifest_hash)
    context_hash = _canonical_hash({
        "input_manifest_id": manifest_id,
        "cutoff_at": training_cutoff,
        "knowledge_mode": "HISTORICAL_RECONSTRUCTION",
        "code_version": __version__,
        "config_version": f"{CONTRACT_VERSION}-frozen-input",
    })
    context_id = _stable_uuid("historical-training-frozen-context", context_hash)
    request = ReconstructionRequest(
        reconstruction_id, signal_session, anchor_session, training_cutoff,
        context_id, manifest_id, manifest_hash, context_hash, universe_version_id,
    )
    request.validate()
    with database.connect() as connection, connection.transaction():
        snapshots = connection.execute(
            """
            SELECT source_snapshot_id, dataset_code, snapshot_kind, parent_snapshot_id,
                   coverage_start, coverage_end, source_available_at
            FROM ops.source_snapshot WHERE source_snapshot_id = ANY(%s::uuid[])
            """,
            ([member.source_snapshot_id for member in ordered],),
        ).fetchall()
        by_id = {row["source_snapshot_id"]: row for row in snapshots}
        if len(by_id) != len(ordered):
            raise HistoricalSafetyError("a requested existing source snapshot is missing")
        for member in ordered:
            row = by_id[member.source_snapshot_id]
            if (
                row["dataset_code"] != member.dataset_code
                or row["snapshot_kind"] != member.snapshot_kind
                or row["parent_snapshot_id"] != member.parent_snapshot_id
                or row["coverage_start"] != member.coverage_start
                or row["coverage_end"] != member.coverage_end
                or row["source_available_at"] > training_cutoff
                or row["coverage_end"] > anchor_session
            ):
                raise HistoricalSafetyError("requested snapshot metadata or cutoff mismatch")
        connection.execute(
            """
            INSERT INTO ops.input_manifest(input_manifest_id, manifest_hash)
            VALUES (%s, %s) ON CONFLICT (manifest_hash) DO NOTHING
            """,
            (manifest_id, manifest_hash),
        )
        for member in ordered:
            connection.execute(
                """
                INSERT INTO ops.input_manifest_member(
                    input_manifest_id, source_snapshot_id, dataset_code, precedence, lineage_role
                ) VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING
                """,
                (
                    manifest_id, member.source_snapshot_id, member.dataset_code,
                    member.precedence, member.lineage_role,
                ),
            )
        connection.execute(
            """
            INSERT INTO ops.execution_context(
                execution_context_id, input_manifest_id, cutoff_at, knowledge_mode,
                code_version, config_version, context_hash
            ) VALUES (%s, %s, %s, 'HISTORICAL_RECONSTRUCTION', %s, %s, %s)
            ON CONFLICT (context_hash) DO NOTHING
            """,
            (
                context_id, manifest_id, training_cutoff, __version__,
                f"{CONTRACT_VERSION}-frozen-input", context_hash,
            ),
        )
        _validate_sources(connection, request)
    return request


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--members-file", type=Path, required=True)
    parser.add_argument("--reconstruction-id", type=uuid.UUID, required=True)
    parser.add_argument("--signal-session", type=date.fromisoformat, required=True)
    parser.add_argument("--anchor-session", type=date.fromisoformat, required=True)
    parser.add_argument("--training-cutoff", type=datetime.fromisoformat, required=True)
    parser.add_argument("--universe-version-id", type=uuid.UUID, required=True)
    args = vars(parser.parse_args())
    payload = json.loads(args.pop("members_file").read_text(encoding="utf-8"))
    members = tuple(
        ManifestSnapshot(
            source_snapshot_id=uuid.UUID(row["source_snapshot_id"]),
            dataset_code=row["dataset_code"],
            snapshot_kind=row["snapshot_kind"],
            lineage_role=row["lineage_role"],
            precedence=row["precedence"],
            parent_snapshot_id=uuid.UUID(row["parent_snapshot_id"])
            if row["parent_snapshot_id"] else None,
            coverage_start=date.fromisoformat(row["coverage_start"]),
            coverage_end=date.fromisoformat(row["coverage_end"]),
        )
        for row in payload
    )
    settings = Settings.from_env()
    request = freeze_training_context(database=Database(settings), members=members, **args)
    print(json.dumps(asdict(request), default=str, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
