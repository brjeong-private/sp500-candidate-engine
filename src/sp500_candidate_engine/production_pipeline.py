from __future__ import annotations

import asyncio
from dataclasses import asdict
from datetime import date, datetime

from sp500_candidate_engine.collectors.alpha_vantage import (
    AlphaVantageEarningsCollector,
)
from sp500_candidate_engine.collectors.massive import MassiveCollector
from sp500_candidate_engine.collectors.sec import SecCollector
from sp500_candidate_engine.collectors.wikipedia import WikipediaUniverseCollector
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database
from sp500_candidate_engine.http import RetryingHttpClient
from sp500_candidate_engine.models import UTC, KnowledgeMode, RunSpec
from sp500_candidate_engine.production_repository import (
    ProductionPersistedRun,
    ProductionRepository,
)
from sp500_candidate_engine.raw_store import RawSnapshotWriter
from sp500_candidate_engine.run_logging import PipelineLogger
from sp500_candidate_engine.source_harness import (
    CandidateCollectionPlan,
    validate_candidate_collection_plan,
)


async def probe_providers(
    settings: Settings,
    *,
    target_date: date,
) -> dict[str, object]:
    if settings.massive_api_key is None:
        raise ValueError("MASSIVE_API_KEY is not configured")
    if settings.alpha_vantage_api_key is None:
        raise ValueError("ALPHA_VANTAGE_API_KEY is not configured")
    async with (
        MassiveCollector(
            base_url=settings.massive_base_url,
            api_key=settings.massive_api_key,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.max_attempts,
            user_agent=settings.http_user_agent,
            requests_per_minute=settings.massive_requests_per_minute,
        ) as massive,
        SecCollector(
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.max_attempts,
            user_agent=settings.http_user_agent,
        ) as sec,
        AlphaVantageEarningsCollector(
            base_url=settings.alpha_vantage_base_url,
            api_key=settings.alpha_vantage_api_key,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.max_attempts,
            user_agent=settings.http_user_agent,
        ) as alpha,
    ):
        massive_result, sec_result, alpha_result = await asyncio.gather(
            massive.probe(target_date),
            sec.probe(),
            alpha.probe(),
        )
    return {
        "massive": massive_result,
        "sec_edgar": sec_result,
        "alpha_vantage": alpha_result,
    }


async def collect_production_inputs(
    settings: Settings,
    *,
    target_date: date,
    knowledge_mode: KnowledgeMode = KnowledgeMode.OPERATIONAL_REPLAY,
) -> ProductionPersistedRun:
    if settings.massive_api_key is None:
        raise ValueError("MASSIVE_API_KEY is not configured")
    if settings.alpha_vantage_api_key is None:
        raise ValueError("ALPHA_VANTAGE_API_KEY is not configured")
    validate_candidate_collection_plan(
        CandidateCollectionPlan(
            target_date=target_date,
            evaluated_on=date.today(),
            massive_requests=4,
            alpha_vantage_requests=1,
            collect_sec_financials=False,
            normalize_sec_financials=True,
        ),
        settings.source_policies(),
    )
    logger = PipelineLogger(settings.log_dir)
    database = Database(settings)
    with logger.stage(target_date, "production_database_migration"):
        await asyncio.to_thread(database.migrate)

    provisional_spec = RunSpec(
        target_date=target_date,
        cutoff_at=datetime.now(UTC),
        knowledge_mode=KnowledgeMode.HISTORICAL_RECONSTRUCTION,
    )
    async with (
        RetryingHttpClient(
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.max_attempts,
            user_agent=settings.http_user_agent,
        ) as reference_client,
        SecCollector(
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.max_attempts,
            user_agent=settings.http_user_agent,
        ) as sec_collector,
        AlphaVantageEarningsCollector(
            base_url=settings.alpha_vantage_base_url,
            api_key=settings.alpha_vantage_api_key,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.max_attempts,
            user_agent=settings.http_user_agent,
        ) as alpha_collector,
    ):
        sec_task = asyncio.create_task(sec_collector.collect_reference())
        alpha_task = asyncio.create_task(alpha_collector.collect())
        with logger.stage(target_date, "production_universe_collection") as stage:
            universe = await WikipediaUniverseCollector(reference_client).collect(provisional_spec)
            stage.add_details(member_count=len(universe.members))
        async with MassiveCollector(
            base_url=settings.massive_base_url,
            api_key=settings.massive_api_key,
            timeout_seconds=settings.http_timeout_seconds,
            max_attempts=settings.max_attempts,
            user_agent=settings.http_user_agent,
            requests_per_minute=settings.massive_requests_per_minute,
        ) as massive_collector:
            with logger.stage(target_date, "massive_collection") as stage:
                massive = await massive_collector.collect(provisional_spec, universe.members)
                stage.add_details(
                    bars=len(massive.bars),
                    actions=len(massive.actions),
                    news=len(massive.news),
                )
                missing_symbols = sorted(
                    {member.symbol for member in universe.members}
                    - {bar.symbol for bar in massive.bars}
                )
                if missing_symbols:
                    stage.add_details(missing_symbols=missing_symbols)
                    stage.mark_partial_success(
                        f"{len(missing_symbols)} Massive bars missing: {', '.join(missing_symbols)}"
                    )
        with logger.stage(target_date, "sec_reference_collection") as stage:
            sec = await sec_task
            stage.add_details(companies=len(sec.companies))
        with logger.stage(target_date, "alpha_earnings_collection") as stage:
            alpha = await alpha_task
            stage.add_details(events=len(alpha.events))

    final_cutoff = max(
        universe.observed_at,
        massive.observed_at,
        sec.observed_at,
        alpha.observed_at,
    )
    run_spec = RunSpec(
        target_date=target_date,
        cutoff_at=final_cutoff,
        knowledge_mode=knowledge_mode,
    )
    writer = RawSnapshotWriter(settings.raw_data_dir)
    payloads = {
        "sp500_universe": universe.sanitized_payload,
        **massive.payloads,
        "sec_company_tickers": sec.payload,
        "alpha_earnings": alpha.payload,
    }
    with logger.stage(target_date, "production_raw_snapshot_write") as stage:
        raw_values = await asyncio.gather(
            *[
                asyncio.to_thread(writer.write, dataset, target_date, payload)
                for dataset, payload in payloads.items()
            ]
        )
        raw_objects = dict(zip(payloads, raw_values, strict=True))
        stage.add_details(snapshot_count=len(raw_objects))

    repository = ProductionRepository(database)
    with logger.stage(target_date, "production_postgres_persistence") as stage:
        result = await asyncio.to_thread(
            repository.persist,
            run_spec=run_spec,
            config_hash=settings.production_config_hash(),
            universe=universe,
            massive=massive,
            sec=sec,
            alpha=alpha,
            raw_objects=raw_objects,
        )
        stage.add_details(**production_result_as_dict(result))
        return result


def production_result_as_dict(result: ProductionPersistedRun) -> dict[str, object]:
    payload = asdict(result)
    return {key: str(value) if hasattr(value, "hex") else value for key, value in payload.items()}
