from __future__ import annotations

import argparse
import asyncio
import json
import uuid
from datetime import date, datetime, timedelta
from importlib.metadata import version
from pathlib import Path

from sp500_candidate_engine.backfill import build_backfill_plan
from sp500_candidate_engine.batch_pipeline import (
    run_backfill_process,
    run_daily_process,
    run_retry_process,
)
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database
from sp500_candidate_engine.models import KnowledgeMode, RunSpec
from sp500_candidate_engine.pipeline import collect_daily_inputs, result_as_dict
from sp500_candidate_engine.process_tracking import ProcessTracker
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


def _datetime(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("datetime must include a UTC offset")
    return parsed


def _mode(value: str) -> KnowledgeMode:
    normalized = value.strip().upper().replace("-", "_")
    return KnowledgeMode(normalized)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="candidate-engine")
    parser.add_argument("--env-file", default=".env")
    commands = parser.add_subparsers(dest="command", required=True)

    stage = commands.add_parser(
        "run-stage", help="Run exactly one pinned candidate stage without collection or training",
    )
    stage.add_argument(
        "--stage", required=True, choices=("QUANTITATIVE", "LLM_PRESELECTION", "FUSION"),
    )
    stage.add_argument("--date", type=_date, required=True)
    stage.add_argument("--execution-context-id", type=uuid.UUID, required=True)
    stage.add_argument("--model-purpose", choices=("SHORT_5D", "MEDIUM_20D"))
    stage.add_argument("--quant-selection-run-id", type=uuid.UUID)
    stage.add_argument("--llm-preselection-run-id", type=uuid.UUID)
    stage.add_argument("--idempotency-key", required=True)
    for name in ("show-stage", "retry-stage"):
        command = commands.add_parser(name, help="Inspect or explicitly retry one candidate stage")
        command.add_argument("--stage-run-id", type=uuid.UUID, required=True)
        if name == "retry-stage":
            command.add_argument("--idempotency-key", required=True)

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

    plan_backfill = commands.add_parser(
        "plan-backfill",
        help="Create a no-network three-month backfill plan",
    )
    plan_backfill.add_argument("--start", type=_date, required=True)
    plan_backfill.add_argument("--end", type=_date, required=True)

    run_daily = commands.add_parser(
        "run-daily",
        help="Run one production date with process tracking and a per-run log",
    )
    run_daily.add_argument("--date", type=_date, required=True)
    run_daily.add_argument(
        "--with-candidates",
        action="store_true",
        help="After successful daily collection, score and select this explicit date",
    )

    export_qlib = commands.add_parser(
        "export-qlib",
        help="Create a manifest-constrained Qlib export for an explicit date range",
    )
    export_qlib.add_argument("--start", type=_date, required=True)
    export_qlib.add_argument("--end", type=_date, required=True)

    build_features = commands.add_parser(
        "build-features",
        help="Validate Alpha158 for an existing Qlib export",
    )
    build_features.add_argument("--export-run-id", type=uuid.UUID, required=True)

    for command_name in ("train-model", "score-date", "select-date", "run-candidates"):
        candidate_command = commands.add_parser(
            command_name,
            help="Run the idempotent model, scoring, and selection workflow for a date",
        )
        candidate_command.add_argument("--date", type=_date, required=True)
        candidate_command.add_argument(
            "--horizon-sessions",
            type=int,
            choices=(5, 20),
            default=5,
        )
        candidate_command.add_argument(
            "--decision-cutoff",
            type=_datetime,
            help="Maximum point-in-time export cutoff, including UTC offset",
        )

    rank_llm = commands.add_parser(
        "rank-llm-candidates",
        help="Generate the manifest-fenced Azure OpenAI analysis-candidate Top 20",
    )
    rank_llm.add_argument("--date", type=_date, required=True)
    rank_llm.add_argument(
        "--execution-context-id", type=uuid.UUID, required=True
    )

    run_backfill = commands.add_parser(
        "run-backfill",
        help="Run a Massive price backfill and automatically retry failed dates",
    )
    run_backfill.add_argument("--start", type=_date, required=True)
    run_backfill.add_argument("--end", type=_date, required=True)
    run_backfill.add_argument(
        "--no-auto-retry",
        action="store_true",
        help="Finish after the initial pass without automatic retries",
    )

    retry_backfill = commands.add_parser(
        "retry-backfill",
        help="Retry failed dates from an earlier process within a date range",
    )
    retry_backfill.add_argument("--process-run-id", type=uuid.UUID, required=True)
    retry_backfill.add_argument("--start", type=_date, required=True)
    retry_backfill.add_argument("--end", type=_date, required=True)

    show_process = commands.add_parser(
        "show-process",
        help="Show current progress for a daily or backfill process",
    )
    show_process.add_argument("--process-run-id", type=uuid.UUID, required=True)

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
    if args.command in {"run-stage", "show-stage", "retry-stage"}:
        from backend.app.schemas.candidate_stages import CandidateStageRequest
        from backend.app.services.candidate_stages import CandidateStageService

        service = CandidateStageService(Database(settings), settings, owner="CLI")
        if args.command == "show-stage":
            print(service.get(args.stage_run_id).model_dump_json(indent=2))
            return
        if args.command == "run-stage":
            accepted = service.accept(CandidateStageRequest(
                stage=args.stage, target_session=args.date,
                execution_context_id=args.execution_context_id, model_purpose=args.model_purpose,
                quant_selection_run_id=args.quant_selection_run_id,
                llm_preselection_run_id=args.llm_preselection_run_id,
            ), args.idempotency_key)
        else:
            accepted = service.retry(args.stage_run_id, args.idempotency_key)
        if not accepted._is_replay:
            asyncio.run(service.execute(accepted.stage_run_id))
        result = service.get(accepted.stage_run_id)
        print(result.model_dump_json(indent=2))
        if result.status in {"FAILED", "SHORTFALL"}:
            raise SystemExit(1)
        return
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

    if args.command == "plan-backfill":
        plan = build_backfill_plan(
            start_date=args.start,
            end_date=args.end,
            evaluated_on=date.today(),
            policies=settings.source_policies(),
        )
        print(json.dumps(plan.as_dict(), indent=2, sort_keys=True))
        return

    if args.command == "run-daily":
        result = asyncio.run(
            run_daily_process(
                settings,
                target_date=args.date,
                run_candidates=args.with_candidates,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    if args.command == "export-qlib":
        from sp500_candidate_engine.analytics.historical_export import (
            HistoricalQlibExportService,
        )

        summary = HistoricalQlibExportService(database).export(
            start_date=args.start,
            end_date=args.end,
            output_root=Path("data/output/qlib"),
            qlib_version=version("pyqlib"),
        )
        print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
        return

    if args.command == "build-features":
        from sp500_candidate_engine.analytics.features import Alpha158FeatureService

        export_dir = Path("data/output/qlib") / str(args.export_run_id)
        manifest = json.loads((export_dir / "manifest.json").read_text(encoding="utf-8"))
        result = Alpha158FeatureService().compute_raw(
            provider_uri=export_dir / "qlib_data",
            instruments="all",
            start_date=_date(manifest["calendar_start"]),
            end_date=_date(manifest["calendar_end"]),
        )
        print(
            json.dumps(
                {
                    "export_run_id": str(args.export_run_id),
                    "rows": len(result.frame),
                    "features": result.expected_dimension,
                },
                indent=2,
                sort_keys=True,
            )
        )
        return

    if args.command in {"train-model", "score-date", "select-date", "run-candidates"}:
        from sp500_candidate_engine.candidate_pipeline import run_candidate_date

        summary = run_candidate_date(
            settings,
            target_date=args.date,
            repository_root=Path(__file__).parents[2],
            horizon_sessions=args.horizon_sessions,
            decision_cutoff=args.decision_cutoff,
        )
        print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
        return

    if args.command == "rank-llm-candidates":
        from sp500_candidate_engine.llm_preselection.pipeline import (
            run_llm_preselection,
        )

        summary = asyncio.run(
            run_llm_preselection(
                settings,
                repository_root=Path(__file__).parents[2],
                target_session=args.date,
                execution_context_id=args.execution_context_id,
            )
        )
        print(json.dumps(summary.__dict__, indent=2, sort_keys=True, default=str))
        return

    if args.command == "run-backfill":
        result = asyncio.run(
            run_backfill_process(
                settings,
                start_date=args.start,
                end_date=args.end,
                auto_retry=not args.no_auto_retry,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    if args.command == "retry-backfill":
        result = asyncio.run(
            run_retry_process(
                settings,
                parent_process_run_id=args.process_run_id,
                start_date=args.start,
                end_date=args.end,
            )
        )
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
        return

    if args.command == "show-process":
        database.migrate()
        with ProcessTracker(database) as tracker:
            result = tracker.get_status(args.process_run_id)
        print(json.dumps(result, indent=2, sort_keys=True, default=str))
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
