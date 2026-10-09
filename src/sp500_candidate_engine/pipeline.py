from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date

from sp500_candidate_engine.collectors.wikipedia import WikipediaUniverseCollector
from sp500_candidate_engine.collectors.yahoo import YahooDailyBarCollector
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database, PersistedRun
from sp500_candidate_engine.http import RetryingHttpClient
from sp500_candidate_engine.models import KnowledgeMode, RunSpec
from sp500_candidate_engine.raw_store import RawSnapshotWriter
from sp500_candidate_engine.run_logging import PipelineLogger


async def collect_daily_inputs(
    settings: Settings,
    *,
    target_date: date,
    mode: KnowledgeMode,
) -> PersistedRun:
    run_spec = RunSpec.for_date(target_date, mode)
    logger = PipelineLogger(settings.log_dir)
    database = Database(settings)
    with logger.stage(target_date, "database_migration", database=settings.pg_database):
        await asyncio.to_thread(database.migrate)

    async with RetryingHttpClient(
        timeout_seconds=settings.http_timeout_seconds,
        max_attempts=settings.max_attempts,
        user_agent=settings.http_user_agent,
    ) as client:
        with logger.stage(target_date, "universe_collection") as stage:
            universe = await WikipediaUniverseCollector(client).collect(run_spec)
            stage.add_details(
                revision_id=universe.revision_id,
                revision_at=universe.revision_at.isoformat(),
                member_count=len(universe.members),
            )
        with logger.stage(
            target_date,
            "market_collection",
            requested_count=len(universe.members),
            max_concurrency=settings.max_concurrency,
        ) as stage:
            market = await YahooDailyBarCollector(
                client,
                max_concurrency=settings.max_concurrency,
                min_success_ratio=settings.min_success_ratio,
            ).collect(run_spec, universe.members)
            stage.add_details(
                received_count=len(market.bars),
                failure_count=len(market.failures),
                failed_symbols=sorted(market.failures),
            )
            if market.failures:
                stage.mark_partial_success(
                    f"{len(market.failures)} symbols failed: {', '.join(sorted(market.failures))}"
                )

    writer = RawSnapshotWriter(settings.raw_data_dir)
    with logger.stage(target_date, "raw_snapshot_write") as stage:
        universe_raw, market_raw = await asyncio.gather(
            asyncio.to_thread(
                writer.write,
                "sp500-universe",
                target_date,
                universe.sanitized_payload,
            ),
            asyncio.to_thread(
                writer.write,
                "daily-bars",
                target_date,
                market.sanitized_payload,
            ),
        )
        stage.add_details(
            universe_content_hash=universe_raw.content_hash,
            market_content_hash=market_raw.content_hash,
        )
    with logger.stage(target_date, "postgres_persistence") as stage:
        result = await asyncio.to_thread(
            database.persist_collection,
            run_spec=run_spec,
            config_hash=settings.collection_config_hash(),
            universe=universe,
            market=market,
            universe_raw=universe_raw,
            market_raw=market_raw,
        )
        stage.add_details(**result_as_dict(result))
        return result


def result_as_dict(result: PersistedRun) -> dict[str, object]:
    payload = asdict(result)
    return {key: str(value) if hasattr(value, "hex") else value for key, value in payload.items()}
