from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Awaitable, Callable
from contextlib import suppress
from datetime import date, datetime
from pathlib import Path
from typing import TypeVar

from sp500_candidate_engine.backfill import (
    backfill_cutoff,
    build_backfill_plan,
    filter_available_supplements,
    previous_backfill_cutoff,
)
from sp500_candidate_engine.backfill_repository import (
    BackfillDateResult,
    BackfillRepository,
)
from sp500_candidate_engine.collectors.massive import MassiveCollector
from sp500_candidate_engine.collectors.sec import SecCollector
from sp500_candidate_engine.collectors.wikipedia import WikipediaUniverseCollector
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database
from sp500_candidate_engine.http import IntervalRateLimiter, RetryingHttpClient
from sp500_candidate_engine.models import UTC, KnowledgeMode, RunSpec
from sp500_candidate_engine.process_tracking import ProcessLogWriter, ProcessTracker
from sp500_candidate_engine.production_models import MassiveBackfillRange
from sp500_candidate_engine.production_pipeline import collect_production_inputs
from sp500_candidate_engine.raw_store import RawSnapshotWriter
from sp500_candidate_engine.sec_bulk import SecBulkResult, parse_sec_bulk

T = TypeVar("T")


async def _run_fatal_process_stage(
    awaitable: Awaitable[T],
    *,
    stage: str,
    process_run_id: uuid.UUID,
    tracker: ProcessTracker,
    writer: ProcessLogWriter,
    heartbeat_seconds: float = 60.0,
) -> T:
    started_at = datetime.now(UTC)
    started_counter = time.perf_counter()
    task = asyncio.ensure_future(awaitable)
    writer.write(
        {
            "process_run_id": str(process_run_id),
            "event_type": "PROCESS_STAGE_START",
            "stage": stage,
            "started_at": started_at.isoformat(),
            "completed": False,
        }
    )
    try:
        sequence = 0
        while True:
            done, _ = await asyncio.wait({task}, timeout=heartbeat_seconds)
            if task in done:
                result = await task
                writer.write(
                    {
                        "process_run_id": str(process_run_id),
                        "event_type": "PROCESS_STAGE_COMPLETE",
                        "stage": stage,
                        "finished_at": datetime.now(UTC).isoformat(),
                        "duration_ms": round(
                            (time.perf_counter() - started_counter) * 1000,
                            3,
                        ),
                        "completed": True,
                    }
                )
                return result
            sequence += 1
            tracker.heartbeat(process_run_id)
            writer.write(
                {
                    "process_run_id": str(process_run_id),
                    "event_type": "PROCESS_HEARTBEAT",
                    "stage": stage,
                    "sequence": sequence,
                    "heartbeat_at": datetime.now(UTC).isoformat(),
                    "duration_ms": round(
                        (time.perf_counter() - started_counter) * 1000,
                        3,
                    ),
                    "completed": False,
                }
            )
    except Exception as error:
        failure_reason = f"{type(error).__name__}: {error}"
        writer.write(
            {
                "process_run_id": str(process_run_id),
                "event_type": "PROCESS_STAGE_FAILURE",
                "stage": stage,
                "finished_at": datetime.now(UTC).isoformat(),
                "duration_ms": round(
                    (time.perf_counter() - started_counter) * 1000,
                    3,
                ),
                "failure_reason": failure_reason,
                "completed": True,
            }
        )
        summary = tracker.finalize(process_run_id)
        writer.write(
            {
                "process_run_id": str(process_run_id),
                "event_type": "PROCESS_COMPLETE",
                "finished_at": datetime.now(UTC).isoformat(),
                "failure_reason": failure_reason,
                "completed": True,
                **summary,
            }
        )
        raise
    finally:
        if not task.done():
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task


async def run_daily_process(
    settings: Settings,
    *,
    target_date: date,
    run_candidates: bool = False,
    process_run_id: uuid.UUID | None = None,
    candidate_history_start: date | None = None,
    candidate_runner: Callable[..., object] | None = None,
) -> dict[str, object]:
    database = Database(settings)
    accepted_run = process_run_id is not None
    if not accepted_run:
        await asyncio.to_thread(database.migrate)
    process_run_id = process_run_id or uuid.uuid4()
    writer = ProcessLogWriter(settings.log_dir, process_run_id)
    with ProcessTracker(database) as tracker:
        if accepted_run:
            tracker.resume_run(process_run_id, log_uri=writer.path.as_uri())
        else:
            tracker.create_run(
                process_run_id=process_run_id,
                process_type="DAILY",
                range_start=target_date,
                range_end=target_date,
                total_dates=1,
                log_uri=writer.path.as_uri(),
                metadata={"pipeline": "collect-production"},
            )
        writer.write(
            {
                "process_run_id": str(process_run_id),
                "event_type": "PROCESS_START",
                "process_type": "DAILY",
                "started_at": datetime.now(UTC).isoformat(),
                "range_start": target_date.isoformat(),
                "range_end": target_date.isoformat(),
                "completed": False,
            }
        )
        handle = tracker.start_attempt(
            process_run_id,
            target_date,
            event_type="COLLECTION",
        )
        try:
            collection_options = {"migrate_database": False} if accepted_run else {}
            result = await collect_production_inputs(
                settings, target_date=target_date, **collection_options
            )
            counts = {
                "universe_members": result.universe_count,
                "changed_bars": result.changed_bars,
                "changed_actions": result.changed_actions,
                "changed_events": result.changed_events,
                "missing_bars": result.missing_bars,
            }
            line = tracker.finish_attempt(
                handle,
                success=True,
                collected_counts=counts,
                failure_reason=None,
            )
        except Exception as error:
            line = tracker.finish_attempt(
                handle,
                success=False,
                collected_counts={},
                failure_reason=f"{type(error).__name__}: {error}",
            )
        writer.write(line)
        summary = tracker.finalize(process_run_id)
        writer.write(
            {
                "process_run_id": str(process_run_id),
                "event_type": "PROCESS_COMPLETE",
                "finished_at": datetime.now(UTC).isoformat(),
                "completed": True,
                **summary,
            }
        )
        response: dict[str, object] = {
            "process_run_id": str(process_run_id),
            "log_file": str(writer.path),
            **summary,
        }
        if run_candidates and summary["status"] == "SUCCEEDED":
            from sp500_candidate_engine.candidate_pipeline import run_candidate_date

            if candidate_history_start is not None:
                from importlib.metadata import version

                from sp500_candidate_engine.analytics.historical_export import (
                    HistoricalQlibExportService,
                )

                await asyncio.to_thread(
                    HistoricalQlibExportService(database).export,
                    start_date=candidate_history_start,
                    end_date=target_date,
                    output_root=Path(__file__).parents[2] / "data" / "output" / "qlib",
                    qlib_version=version("pyqlib"),
                )
            candidate = await asyncio.to_thread(
                candidate_runner or run_candidate_date,
                settings,
                target_date=target_date,
                repository_root=Path(__file__).parents[2],
            )
            response["candidate_run"] = {
                "price_session_date": candidate.price_session_date,
                "model_version_id": candidate.model_version_id,
                "scoring_run_id": candidate.scoring_run_id,
                "selection_run_id": candidate.selection_run_id,
                "candidate_count": candidate.candidate_count,
                "model_status": getattr(candidate, "model_status", "SHADOW"),
                "promotion_gate_passed": candidate.promotion_gate_passed,
            }
        return response


async def run_backfill_process(
    settings: Settings,
    *,
    start_date: date,
    end_date: date,
    auto_retry: bool = True,
    process_run_id: uuid.UUID | None = None,
) -> dict[str, object]:
    plan = build_backfill_plan(
        start_date=start_date,
        end_date=end_date,
        evaluated_on=date.today(),
        policies=settings.source_policies(),
    )
    result = await _run_backfill_dates(
        settings,
        process_type="BACKFILL",
        dates=plan.sessions,
        range_start=start_date,
        range_end=end_date,
        metadata={"plan": plan.as_dict()},
        auto_retry=auto_retry,
        process_run_id=process_run_id,
    )
    return result


async def run_retry_process(
    settings: Settings,
    *,
    parent_process_run_id: uuid.UUID,
    start_date: date,
    end_date: date,
) -> dict[str, object]:
    database = Database(settings)
    await asyncio.to_thread(database.migrate)
    with ProcessTracker(database) as tracker:
        recovered_attempts = tracker.recover_stale_attempts(parent_process_run_id)
        retry_dates = tracker.dates_for_retry(
            parent_process_run_id,
            start_date=start_date,
            end_date=end_date,
        )
    if not retry_dates:
        return {
            "parent_process_run_id": str(parent_process_run_id),
            "status": "NO_RETRY_REQUIRED",
            "dates": [],
            "recovered_stale_attempts": recovered_attempts,
        }
    result = await _run_backfill_dates(
        settings,
        process_type="BACKFILL_RETRY",
        dates=retry_dates,
        range_start=start_date,
        range_end=end_date,
        metadata={
            "parent_process_run_id": str(parent_process_run_id),
            "recovered_stale_attempts": recovered_attempts,
        },
        auto_retry=False,
    )
    return {
        **result,
        "parent_process_run_id": str(parent_process_run_id),
        "recovered_stale_attempts": recovered_attempts,
    }


async def _run_backfill_dates(
    settings: Settings,
    *,
    process_type: str,
    dates: tuple[date, ...],
    range_start: date,
    range_end: date,
    metadata: dict[str, object],
    auto_retry: bool,
    process_run_id: uuid.UUID | None = None,
) -> dict[str, object]:
    if settings.massive_api_key is None:
        raise ValueError("MASSIVE_API_KEY is not configured")
    database = Database(settings)
    accepted_run = process_run_id is not None
    if not accepted_run:
        await asyncio.to_thread(database.migrate)
    process_run_id = process_run_id or uuid.uuid4()
    writer = ProcessLogWriter(settings.log_dir, process_run_id)
    raw_writer = RawSnapshotWriter(settings.raw_data_dir)
    repository = BackfillRepository(database)
    with ProcessTracker(database) as tracker:
        if accepted_run:
            tracker.resume_run(process_run_id, log_uri=writer.path.as_uri())
        else:
            tracker.create_run(
                process_run_id=process_run_id,
                process_type=process_type,
                range_start=range_start,
                range_end=range_end,
                total_dates=len(dates),
                log_uri=writer.path.as_uri(),
                metadata=metadata,
            )
        writer.write(
            {
                "process_run_id": str(process_run_id),
                "event_type": "PROCESS_START",
                "process_type": process_type,
                "started_at": datetime.now(UTC).isoformat(),
                "range_start": range_start.isoformat(),
                "range_end": range_end.isoformat(),
                "total_dates": len(dates),
                "completed": False,
            }
        )
        async with (
            RetryingHttpClient(
                timeout_seconds=settings.http_timeout_seconds,
                max_attempts=settings.max_attempts,
                user_agent=settings.http_user_agent,
                limiter=IntervalRateLimiter(60),
            ) as reference_client,
            MassiveCollector(
                base_url=settings.massive_base_url,
                api_key=settings.massive_api_key,
                timeout_seconds=settings.http_timeout_seconds,
                max_attempts=settings.max_attempts,
                user_agent=settings.http_user_agent,
                requests_per_minute=settings.massive_requests_per_minute,
            ) as massive,
            SecCollector(
                timeout_seconds=max(settings.http_timeout_seconds, 300),
                max_attempts=settings.max_attempts,
                user_agent=settings.http_user_agent,
            ) as sec_collector,
        ):
            range_started = datetime.now(UTC)
            range_counter = time.perf_counter()
            range_spec = RunSpec(
                target_date=range_end,
                cutoff_at=backfill_cutoff(range_end),
                knowledge_mode=KnowledgeMode.HISTORICAL_RECONSTRUCTION,
            )
            range_universe = await WikipediaUniverseCollector(reference_client).collect(range_spec)
            range_data_task = asyncio.create_task(
                massive.collect_backfill_range(
                    start_date=range_start,
                    end_date=range_end,
                    members=range_universe.members,
                )
            )
            submissions_task = asyncio.create_task(
                sec_collector.download_bulk("sec_submissions_bulk")
            )
            companyfacts_task = asyncio.create_task(
                sec_collector.download_bulk("sec_companyfacts_bulk")
            )
            range_data, submissions_zip, companyfacts_zip = await _run_fatal_process_stage(
                asyncio.gather(
                    range_data_task,
                    submissions_task,
                    companyfacts_task,
                ),
                stage="RANGE_DOWNLOAD",
                process_run_id=process_run_id,
                tracker=tracker,
                writer=writer,
            )
            allowed_ciks = tuple(member.cik for member in range_universe.members if member.cik)
            sec_result = await _run_fatal_process_stage(
                asyncio.to_thread(
                    parse_sec_bulk,
                    submissions_zip,
                    companyfacts_zip,
                    allowed_ciks=allowed_ciks,
                    cutoff_at=backfill_cutoff(range_end),
                ),
                stage="SEC_PARSE",
                process_run_id=process_run_id,
                tracker=tracker,
                writer=writer,
            )
            range_raw_values = await asyncio.gather(
                *[
                    asyncio.to_thread(
                        raw_writer.write,
                        dataset,
                        range_end,
                        payload,
                    )
                    for dataset, payload in range_data.payloads.items()
                ]
            )
            range_raw_objects = dict(zip(range_data.payloads, range_raw_values, strict=True))
            submissions_raw, companyfacts_raw = await asyncio.gather(
                asyncio.to_thread(
                    raw_writer.write_bytes,
                    "sec_submissions_bulk",
                    range_end,
                    submissions_zip,
                    extension="zip",
                ),
                asyncio.to_thread(
                    raw_writer.write_bytes,
                    "sec_companyfacts_bulk",
                    range_end,
                    companyfacts_zip,
                    extension="zip",
                ),
            )
            range_raw_objects.update(
                {
                    "sec_submissions_bulk": submissions_raw,
                    "sec_companyfacts_bulk": companyfacts_raw,
                }
            )
            source_definitions = {
                dataset: (
                    "MASSIVE_STOCKS",
                    "Massive Stocks API",
                    "https://api.massive.com",
                    "PROVIDER_TERMS_REQUIRED",
                )
                for dataset in range_data.payloads
            }
            source_definitions.update(
                {
                    "sec_submissions_bulk": (
                        "SEC_EDGAR",
                        "SEC EDGAR",
                        "https://data.sec.gov",
                        "PUBLIC_GOVERNMENT_DATA",
                    ),
                    "sec_companyfacts_bulk": (
                        "SEC_EDGAR",
                        "SEC EDGAR",
                        "https://data.sec.gov",
                        "PUBLIC_GOVERNMENT_DATA",
                    ),
                }
            )
            tracker_connection = tracker.active_connection()
            with tracker_connection.transaction():
                parent_snapshot_ids = repository.persist_parent_range(
                    connection=tracker_connection,
                    start_date=range_start,
                    end_date=range_end,
                    observed_at=range_data.observed_at,
                    raw_objects=range_raw_objects,
                    source_definitions=source_definitions,
                )
            writer.write(
                {
                    "process_run_id": str(process_run_id),
                    "event_type": "RANGE_COLLECTION",
                    "pipeline_started_at": range_started.isoformat(),
                    "collection_date": None,
                    "range_start": range_start.isoformat(),
                    "range_end": range_end.isoformat(),
                    "duration_ms": round(
                        (time.perf_counter() - range_counter) * 1000,
                        3,
                    ),
                    "collected_counts": {
                        "actions": len(range_data.actions),
                        "news": len(range_data.news),
                        "raw_snapshots": len(range_raw_objects),
                        "sec_filings": len(sec_result.filings),
                        "sec_facts": len(sec_result.facts),
                    },
                    "status": "SUCCESS",
                    "failure_reason": None,
                    "retry_required": False,
                    "retry_status": "NOT_REQUIRED",
                    "completed": True,
                }
            )
            await _run_date_attempts(
                settings,
                dates=dates,
                event_type="COLLECTION",
                process_run_id=process_run_id,
                tracker=tracker,
                writer=writer,
                reference_client=reference_client,
                massive=massive,
                raw_writer=raw_writer,
                repository=repository,
                range_data=range_data,
                parent_snapshot_ids=parent_snapshot_ids,
                sec_result=sec_result,
            )
            retry_dates = tracker.dates_for_retry(
                process_run_id,
                start_date=range_start,
                end_date=range_end,
            )
            writer.write(
                {
                    "process_run_id": str(process_run_id),
                    "event_type": "RETRY_CHECK",
                    "checked_at": datetime.now(UTC).isoformat(),
                    "retry_required": bool(retry_dates),
                    "retry_dates": [value.isoformat() for value in retry_dates],
                    "completed": False,
                }
            )
            if auto_retry and retry_dates:
                await _run_date_attempts(
                    settings,
                    dates=retry_dates,
                    event_type="RETRY",
                    process_run_id=process_run_id,
                    tracker=tracker,
                    writer=writer,
                    reference_client=reference_client,
                    massive=massive,
                    raw_writer=raw_writer,
                    repository=repository,
                    range_data=range_data,
                    parent_snapshot_ids=parent_snapshot_ids,
                    sec_result=sec_result,
                )
        summary = tracker.finalize(process_run_id)
        writer.write(
            {
                "process_run_id": str(process_run_id),
                "event_type": "PROCESS_COMPLETE",
                "finished_at": datetime.now(UTC).isoformat(),
                "completed": True,
                **summary,
            }
        )
        return {
            "process_run_id": str(process_run_id),
            "log_file": str(writer.path),
            **summary,
        }


async def _run_date_attempts(
    settings: Settings,
    *,
    dates: tuple[date, ...],
    event_type: str,
    process_run_id: uuid.UUID,
    tracker: ProcessTracker,
    writer: ProcessLogWriter,
    reference_client: RetryingHttpClient,
    massive: MassiveCollector,
    raw_writer: RawSnapshotWriter,
    repository: BackfillRepository,
    range_data: MassiveBackfillRange,
    parent_snapshot_ids: dict[str, uuid.UUID],
    sec_result: SecBulkResult,
) -> None:
    for collection_date in dates:
        handle = tracker.start_attempt(
            process_run_id,
            collection_date,
            event_type=event_type,
        )
        try:
            result = await _collect_backfill_date(
                settings,
                collection_date=collection_date,
                reference_client=reference_client,
                massive=massive,
                raw_writer=raw_writer,
                repository=repository,
                tracker=tracker,
                range_data=range_data,
                parent_snapshot_ids=parent_snapshot_ids,
                sec_result=sec_result,
            )
            line = tracker.finish_attempt(
                handle,
                success=True,
                collected_counts=result.collected_counts(),
                failure_reason=None,
            )
        except Exception as error:
            line = tracker.finish_attempt(
                handle,
                success=False,
                collected_counts={},
                failure_reason=f"{type(error).__name__}: {error}",
            )
        writer.write(line)


async def _collect_backfill_date(
    settings: Settings,
    *,
    collection_date: date,
    reference_client: RetryingHttpClient,
    massive: MassiveCollector,
    raw_writer: RawSnapshotWriter,
    repository: BackfillRepository,
    tracker: ProcessTracker,
    range_data: MassiveBackfillRange,
    parent_snapshot_ids: dict[str, uuid.UUID],
    sec_result: SecBulkResult,
) -> BackfillDateResult:
    run_spec = RunSpec(
        target_date=collection_date,
        cutoff_at=backfill_cutoff(collection_date),
        knowledge_mode=KnowledgeMode.HISTORICAL_RECONSTRUCTION,
    )
    universe = await WikipediaUniverseCollector(reference_client).collect(run_spec)
    market = await massive.collect_grouped_daily(run_spec, universe.members)
    universe_raw, market_raw = await asyncio.gather(
        asyncio.to_thread(
            raw_writer.write,
            "sp500-universe-backfill",
            collection_date,
            universe.sanitized_payload,
        ),
        asyncio.to_thread(
            raw_writer.write,
            "massive-grouped-daily-backfill",
            collection_date,
            market.sanitized_payload,
        ),
    )
    visible_actions, visible_news = filter_available_supplements(
        actions=range_data.actions,
        news=range_data.news,
        cutoff_at=run_spec.cutoff_at,
        after_at=previous_backfill_cutoff(collection_date),
    )
    dividend_rows = [
        action.metadata for action in visible_actions if action.action_type == "DIVIDEND"
    ]
    split_rows = [action.metadata for action in visible_actions if action.action_type == "SPLIT"]
    supplement_payloads = {
        "massive_dividends_backfill_derived": {
            "cutoff_at": run_spec.cutoff_at.isoformat(),
            "results": dividend_rows,
        },
        "massive_splits_backfill_derived": {
            "cutoff_at": run_spec.cutoff_at.isoformat(),
            "results": split_rows,
        },
        "massive_news_backfill_derived": {
            "cutoff_at": run_spec.cutoff_at.isoformat(),
            "results": [news.metadata for news in visible_news],
        },
    }
    supplement_values = await asyncio.gather(
        *[
            asyncio.to_thread(
                raw_writer.write,
                dataset,
                collection_date,
                payload,
            )
            for dataset, payload in supplement_payloads.items()
        ]
    )
    supplement_raw = dict(zip(supplement_payloads, supplement_values, strict=True))
    connection = tracker.active_connection()
    result = repository.persist_price_date(
        run_spec=run_spec,
        config_hash=settings.production_config_hash(),
        universe=universe,
        market=market,
        universe_raw=universe_raw,
        market_raw=market_raw,
        connection=connection,
    )
    with connection.transaction():
        result = repository.persist_massive_supplements(
            connection=connection,
            run_spec=run_spec,
            result=result,
            actions=visible_actions,
            news=visible_news,
            raw_objects={
                "sp500_universe_backfill": universe_raw,
                "massive_grouped_daily_backfill": market_raw,
                **supplement_raw,
            },
            observed_at=range_data.observed_at,
            parent_snapshot_ids=parent_snapshot_ids,
        )
    previous_cutoff = previous_backfill_cutoff(collection_date)
    visible_filings = tuple(
        filing
        for filing in sec_result.filings
        if previous_cutoff < filing.accepted_at <= run_spec.cutoff_at
    )
    visible_accessions = {filing.accession for filing in visible_filings}
    visible_facts = tuple(
        fact
        for fact in sec_result.facts
        if previous_cutoff < fact.accepted_at <= run_spec.cutoff_at
        and fact.accession in visible_accessions
    )
    daily_sec_result = SecBulkResult(
        filings=visible_filings,
        facts=visible_facts,
        summary={
            "filings": len(visible_filings),
            "facts": len(visible_facts),
        },
    )
    sec_payloads = {
        "sec_filings_backfill_derived": {
            "cutoff_at": run_spec.cutoff_at.isoformat(),
            "filings": [
                {
                    "cik": filing.cik,
                    "accession": filing.accession,
                    "accepted_at": filing.accepted_at.isoformat(),
                    "period": filing.period.isoformat() if filing.period else None,
                    "filed": filing.filed.isoformat(),
                    "form": filing.form,
                    "primary_document": filing.primary_document,
                    "primary_document_url": filing.primary_document_url,
                    "amendment": filing.amendment,
                }
                for filing in visible_filings
            ],
        },
        "sec_facts_backfill_derived": {
            "cutoff_at": run_spec.cutoff_at.isoformat(),
            "facts": [
                {
                    "cik": fact.cik,
                    "accession": fact.accession,
                    "accepted_at": fact.accepted_at.isoformat(),
                    "taxonomy": fact.taxonomy,
                    "concept": fact.concept,
                    "value": str(fact.value),
                    "unit": fact.unit,
                    "period_start": (fact.period_start.isoformat() if fact.period_start else None),
                    "period_end": fact.period_end.isoformat(),
                    "context_type": fact.context_type,
                    "duration_days": fact.duration_days,
                    "form": fact.form,
                    "fy": fact.fy,
                    "fp": fact.fp,
                    "frame": fact.frame,
                    "decimals": fact.decimals,
                    "amendment": fact.amendment,
                    "context_hash": fact.context_hash,
                }
                for fact in visible_facts
            ],
        },
    }
    sec_raw_values = await asyncio.gather(
        *[
            asyncio.to_thread(
                raw_writer.write,
                dataset,
                collection_date,
                payload,
            )
            for dataset, payload in sec_payloads.items()
        ]
    )
    sec_raw = dict(zip(sec_payloads, sec_raw_values, strict=True))
    with connection.transaction():
        return repository.persist_sec_supplements(
            connection=connection,
            run_spec=run_spec,
            result=result,
            sec_result=daily_sec_result,
            raw_objects={
                "sp500_universe_backfill": universe_raw,
                "massive_grouped_daily_backfill": market_raw,
                **supplement_raw,
                **sec_raw,
            },
            observed_at=datetime.now(UTC),
            parent_snapshot_ids=parent_snapshot_ids,
        )
