from __future__ import annotations

import argparse
import asyncio
import json
from datetime import date, timedelta

from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database
from sp500_candidate_engine.models import KnowledgeMode, RunSpec
from sp500_candidate_engine.pipeline import collect_daily_inputs, result_as_dict
from sp500_candidate_engine.production_pipeline import (
    collect_production_inputs,
    probe_providers,
    production_result_as_dict,
)
from sp500_candidate_engine.raw_store import RawSnapshotWriter
from sp500_candidate_engine.run_logging import PipelineLogger
from sp500_candidate_engine.source_harness import (
    CandidateCollectionPlan,
    validate_candidate_collection_plan,
)
from sp500_candidate_engine.temporal import FutureDataViolation, TemporalFence


def _date(value: str) -> date:
    return date.fromisoformat(value)


def _mode(value: str) -> KnowledgeMode:
    normalized = value.strip().upper().replace("-", "_")
    return KnowledgeMode(normalized)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candidate-engine")
    parser.add_argument("--env-file", default=".env")
    commands = parser.add_subparsers(dest="command", required=True)

    commands.add_parser("migrate", help="Apply the MVP PostgreSQL schema")
    commands.add_parser(
        "check-config",
        help="Show provider selection and whether required keys are configured",
    )
    source_harness = commands.add_parser(
        "check-source-harness",
        help="Validate provider limits for a candidate collection run",
    )
    source_harness.add_argument("--date", type=_date, required=True)
    source_harness.add_argument("--massive-requests", type=int, default=503)

    collect = commands.add_parser("collect", help="Collect a point-in-time daily input batch")
    collect.add_argument("--date", type=_date, required=True)
    collect.add_argument(
        "--mode",
        type=_mode,
        default=KnowledgeMode.HISTORICAL_RECONSTRUCTION,
    )
    collect_production = commands.add_parser(
        "collect-production",
        help="Collect Massive, SEC, and Alpha Vantage daily inputs",
    )
    collect_production.add_argument("--date", type=_date, required=True)

    probe = commands.add_parser(
        "probe-providers",
        help="Probe Massive, SEC, and Alpha Vantage without exposing keys",
    )
    probe.add_argument("--date", type=_date, required=True)

    verify = commands.add_parser("verify-cutoff", help="Run app and database temporal fences")
    verify.add_argument("--date", type=_date, required=True)
    verify.add_argument(
        "--mode",
        type=_mode,
        default=KnowledgeMode.HISTORICAL_RECONSTRUCTION,
    )

    inspect = commands.add_parser("inspect-date", help="Inspect rows loaded for a date")
    inspect.add_argument("--date", type=_date, required=True)

    reset = commands.add_parser("reset-date", help="Delete exactly one collection date")
    reset.add_argument("--date", type=_date, required=True)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    settings = Settings.from_env(args.env_file)
    database = Database(settings)

    if args.command == "migrate":
        database.migrate()
        print(json.dumps({"status": "migrated", "database": settings.pg_database}))
        return

    if args.command == "check-config":
        print(
            json.dumps(
                {
                    "providers": settings.provider_status(),
                    "source_policies": settings.source_policies().as_dict(),
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command == "check-source-harness":
        result = validate_candidate_collection_plan(
            CandidateCollectionPlan(
                target_date=args.date,
                evaluated_on=date.today(),
                massive_requests=args.massive_requests,
                alpha_vantage_requests=1,
                alpha_vantage_symbol_filter=None,
                collect_sec_financials=True,
                normalize_sec_financials=True,
            ),
            settings.source_policies(),
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.command == "collect":
        result = asyncio.run(collect_daily_inputs(settings, target_date=args.date, mode=args.mode))
        print(json.dumps(result_as_dict(result), indent=2, sort_keys=True))
        return

    if args.command == "collect-production":
        result = asyncio.run(collect_production_inputs(settings, target_date=args.date))
        print(json.dumps(production_result_as_dict(result), indent=2, sort_keys=True))
        return

    if args.command == "probe-providers":
        result = asyncio.run(probe_providers(settings, target_date=args.date))
        print(json.dumps(result, indent=2, sort_keys=True))
        return

    if args.command == "verify-cutoff":
        run_spec = RunSpec.for_date(args.date, args.mode)
        fence = TemporalFence(run_spec)
        try:
            fence.require_session_date(args.date + timedelta(days=1))
        except FutureDataViolation:
            app_fence = True
        else:
            app_fence = False
        database.migrate()
        db_fence = database.verify_database_fence(run_spec)
        loaded = database.verify_loaded_date(args.date)
        if int(loaded["future_rows"] or 0) != 0:
            raise FutureDataViolation(f"Database contains future rows: {loaded}")
        print(
            json.dumps(
                {
                    "application_fence_rejected_future_date": app_fence,
                    "database_fence_rejected_future_coverage": db_fence,
                    "loaded": loaded,
                },
                indent=2,
                default=str,
                sort_keys=True,
            )
        )
        return

    if args.command == "inspect-date":
        print(
            json.dumps(
                database.verify_loaded_date(args.date),
                indent=2,
                default=str,
                sort_keys=True,
            )
        )
        return

    if args.command == "reset-date":
        logger = PipelineLogger(settings.log_dir)
        with logger.stage(args.date, "reset_collection_date") as stage:
            database.migrate()
            counts = database.delete_collection_date(args.date)
            raw_files = RawSnapshotWriter(settings.raw_data_dir).delete_date(args.date)
            stage.add_details(**counts, raw_files=raw_files)
        print(
            json.dumps(
                {**counts, "raw_files": raw_files},
                indent=2,
                sort_keys=True,
            )
        )
        return

    raise AssertionError(f"Unhandled command: {args.command}")
