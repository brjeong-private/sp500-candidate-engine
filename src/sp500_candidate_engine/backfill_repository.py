from __future__ import annotations

import uuid
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import date, datetime

from psycopg import Connection

from sp500_candidate_engine.database import (
    Database,
    _canonical_hash,
    _run_config_hash,
    _stable_uuid,
)
from sp500_candidate_engine.models import (
    KnowledgeMode,
    MarketCollection,
    RunSpec,
    UniverseCollection,
)
from sp500_candidate_engine.production_models import CorporateAction, NewsItem
from sp500_candidate_engine.production_repository import ProductionRepository
from sp500_candidate_engine.raw_store import RawObject
from sp500_candidate_engine.sec_bulk import SecBulkResult


@dataclass(frozen=True)
class BackfillDateResult:
    ingestion_run_id: uuid.UUID
    input_manifest_id: uuid.UUID
    execution_context_id: uuid.UUID
    universe_version_id: uuid.UUID
    universe_count: int
    collected_bars: int
    changed_bars: int
    missing_bars: int
    universe_snapshot_id: uuid.UUID
    market_snapshot_id: uuid.UUID
    changed_actions: int = 0
    changed_events: int = 0
    collected_actions: int = 0
    collected_events: int = 0
    changed_filings: int = 0
    changed_facts: int = 0
    collected_filings: int = 0
    collected_facts: int = 0

    def collected_counts(self) -> dict[str, int]:
        return {
            "universe_members": self.universe_count,
            "bars": self.collected_bars,
            "changed_bars": self.changed_bars,
            "missing_bars": self.missing_bars,
            "changed_actions": self.changed_actions,
            "changed_events": self.changed_events,
            "actions": self.collected_actions,
            "events": self.collected_events,
            "changed_filings": self.changed_filings,
            "changed_facts": self.changed_facts,
            "filings": self.collected_filings,
            "facts": self.collected_facts,
        }


class BackfillRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def persist_price_date(
        self,
        *,
        run_spec: RunSpec,
        config_hash: str,
        universe: UniverseCollection,
        market: MarketCollection,
        universe_raw: RawObject,
        market_raw: RawObject,
        connection: Connection[dict[str, object]] | None = None,
    ) -> BackfillDateResult:
        if run_spec.knowledge_mode is not KnowledgeMode.HISTORICAL_RECONSTRUCTION:
            raise ValueError("Backfill persistence requires HISTORICAL_RECONSTRUCTION")
        run_key = _canonical_hash(
            {
                "base": _run_config_hash(config_hash, run_spec.knowledge_mode),
                "pipeline": "massive_price_backfill",
            }
        )
        connection_context = (
            self.database.connect() if connection is None else nullcontext(connection)
        )
        with connection_context as active_connection, active_connection.transaction():
            run_id = self._start_run(
                active_connection,
                run_spec,
                run_key,
                len(universe.members),
            )
            wiki_source_id = Database._upsert_source(
                active_connection,
                "WIKIPEDIA_REVISION",
                "Wikipedia revision API",
                "https://en.wikipedia.org/w/api.php",
                "PUBLIC_REFERENCE",
            )
            massive_source_id = Database._upsert_source(
                active_connection,
                "MASSIVE_STOCKS",
                "Massive Stocks API",
                "https://api.massive.com",
                "PROVIDER_TERMS_REQUIRED",
            )
            universe_snapshot_id = Database._upsert_snapshot(
                connection=active_connection,
                run_id=run_id,
                source_id=wiki_source_id,
                dataset_code="sp500_universe_backfill",
                target_date=run_spec.target_date,
                as_of_at=universe.revision_at,
                fetched_at=universe.observed_at,
                source_available_at=universe.revision_at,
                availability_basis="WIKIPEDIA_REVISION_TIMESTAMP",
                raw=universe_raw,
                is_reconstruction=True,
            )
            market_snapshot_id = Database._upsert_snapshot(
                connection=active_connection,
                run_id=run_id,
                source_id=massive_source_id,
                dataset_code="massive_grouped_daily_backfill",
                target_date=run_spec.target_date,
                as_of_at=run_spec.cutoff_at,
                fetched_at=market.observed_at,
                source_available_at=market.source_available_at,
                availability_basis="ASSUMED_16_15_AMERICA_NEW_YORK",
                raw=market_raw,
                is_reconstruction=True,
            )
            universe_version_id, instrument_ids = Database._persist_universe(
                active_connection,
                run_spec,
                universe,
                universe_snapshot_id,
            )
            changed_bars = Database._persist_bars(
                active_connection,
                market.bars,
                instrument_ids,
                massive_source_id,
                market_snapshot_id,
                market.source_available_at,
                market.observed_at,
            )
            missing_symbols = sorted(market.failures)
            ProductionRepository._persist_missing_bar_issues(
                active_connection,
                run_id,
                missing_symbols,
                "massive_grouped_daily_backfill",
            )
            snapshots = {
                "sp500_universe_backfill": universe_snapshot_id,
                "massive_grouped_daily_backfill": market_snapshot_id,
            }
            raw_objects = {
                "sp500_universe_backfill": universe_raw,
                "massive_grouped_daily_backfill": market_raw,
            }
            manifest_id, context_id = ProductionRepository._persist_manifest(
                active_connection,
                run_spec,
                run_key,
                snapshots,
                raw_objects,
            )
            active_connection.execute(
                """
                UPDATE ops.ingestion_run
                   SET status = 'SUCCEEDED',
                       received_count = %s,
                       inserted_count = %s,
                       error_count = %s,
                       finished_at = now()
                 WHERE ingestion_run_id = %s
                """,
                (len(market.bars), changed_bars, len(missing_symbols), run_id),
            )
            return BackfillDateResult(
                ingestion_run_id=run_id,
                input_manifest_id=manifest_id,
                execution_context_id=context_id,
                universe_version_id=universe_version_id,
                universe_count=len(universe.members),
                collected_bars=len(market.bars),
                changed_bars=changed_bars,
                missing_bars=len(missing_symbols),
                universe_snapshot_id=universe_snapshot_id,
                market_snapshot_id=market_snapshot_id,
            )

    def persist_parent_range(
        self,
        *,
        connection: Connection[dict[str, object]],
        start_date: date,
        end_date: date,
        observed_at: datetime,
        raw_objects: dict[str, RawObject],
        source_definitions: dict[str, tuple[str, str, str, str]],
    ) -> dict[str, uuid.UUID]:
        run_key = _canonical_hash(
            {
                "pipeline": "maximum_data_backfill_range",
                "start_date": start_date.isoformat(),
                "end_date": end_date.isoformat(),
                "content_hashes": {
                    dataset: raw.content_hash for dataset, raw in sorted(raw_objects.items())
                },
            }
        )
        existing = connection.execute(
            """
            SELECT ingestion_run_id
            FROM ops.ingestion_run
            WHERE dataset_code = 'maximum_data_backfill_range'
              AND target_date = %s
              AND config_hash = %s
            """,
            (end_date, run_key),
        ).fetchone()
        if existing is None:
            run_id = uuid.uuid4()
            connection.execute(
                """
                INSERT INTO ops.ingestion_run(
                    ingestion_run_id, dataset_code, target_date, cutoff_at,
                    knowledge_mode, config_hash, status, requested_count,
                    received_count, inserted_count, finished_at
                )
                VALUES (
                    %s, 'maximum_data_backfill_range', %s, %s,
                    'HISTORICAL_RECONSTRUCTION', %s, 'SUCCEEDED',
                    %s, %s, %s, now()
                )
                """,
                (
                    run_id,
                    end_date,
                    observed_at,
                    run_key,
                    len(raw_objects),
                    len(raw_objects),
                    len(raw_objects),
                ),
            )
        else:
            run_id = existing["ingestion_run_id"]
        snapshots: dict[str, uuid.UUID] = {}
        for dataset, raw in sorted(raw_objects.items()):
            source_code, source_name, base_url, license_class = source_definitions[dataset]
            source_id = Database._upsert_source(
                connection,
                source_code,
                source_name,
                base_url,
                license_class,
            )
            snapshot_id = _stable_uuid(
                "source-snapshot-range",
                f"{source_id}:{dataset}:{start_date}:{end_date}:{raw.content_hash}",
            )
            inserted = connection.execute(
                """
                INSERT INTO ops.source_snapshot(
                    source_snapshot_id, ingestion_run_id, source_id, dataset_code,
                    snapshot_kind, coverage_start, coverage_end, as_of_at,
                    fetched_at, source_available_at, storage_uri, content_hash,
                    byte_size, license_class, is_reconstruction,
                    availability_basis
                )
                VALUES (
                    %s, %s, %s, %s, 'FULL', %s, %s, %s,
                    %s, %s, %s, %s, %s,
                    'PROVIDER_TERMS', true, 'BACKFILL_PARENT_RANGE'
                )
                ON CONFLICT (
                    source_id, dataset_code, coverage_start, coverage_end, content_hash
                ) DO NOTHING
                RETURNING source_snapshot_id
                """,
                (
                    snapshot_id,
                    run_id,
                    source_id,
                    dataset,
                    start_date,
                    end_date,
                    observed_at,
                    observed_at,
                    observed_at,
                    raw.uri,
                    raw.content_hash,
                    raw.byte_size,
                ),
            ).fetchone()
            if inserted is not None:
                snapshots[dataset] = inserted["source_snapshot_id"]
                continue
            row = connection.execute(
                """
                SELECT source_snapshot_id
                FROM ops.source_snapshot
                WHERE source_id = %s
                  AND dataset_code = %s
                  AND coverage_start = %s
                  AND coverage_end = %s
                  AND content_hash = %s
                """,
                (source_id, dataset, start_date, end_date, raw.content_hash),
            ).fetchone()
            if row is None:
                raise RuntimeError("Could not resolve parent range snapshot")
            snapshots[dataset] = row["source_snapshot_id"]
        return snapshots

    def persist_sec_supplements(
        self,
        *,
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        result: BackfillDateResult,
        sec_result: SecBulkResult,
        raw_objects: dict[str, RawObject],
        observed_at: datetime,
        parent_snapshot_ids: dict[str, uuid.UUID],
    ) -> BackfillDateResult:
        sec_source_id = Database._upsert_source(
            connection,
            "SEC_EDGAR",
            "SEC EDGAR",
            "https://data.sec.gov",
            "PUBLIC_GOVERNMENT_DATA",
        )
        filing_snapshot_id = self._persist_derived_snapshot(
            connection=connection,
            run_spec=run_spec,
            run_id=result.ingestion_run_id,
            source_id=sec_source_id,
            dataset_code="sec_filings_backfill_derived",
            raw=raw_objects["sec_filings_backfill_derived"],
            observed_at=observed_at,
            parent_snapshot_id=parent_snapshot_ids["sec_submissions_bulk"],
        )
        fact_snapshot_id = self._persist_derived_snapshot(
            connection=connection,
            run_spec=run_spec,
            run_id=result.ingestion_run_id,
            source_id=sec_source_id,
            dataset_code="sec_facts_backfill_derived",
            raw=raw_objects["sec_facts_backfill_derived"],
            observed_at=observed_at,
            parent_snapshot_id=parent_snapshot_ids["sec_companyfacts_bulk"],
        )
        issuer_rows = connection.execute(
            "SELECT issuer_id, cik FROM ref.issuer WHERE cik IS NOT NULL"
        ).fetchall()
        issuer_ids = {str(row["cik"]).zfill(10): row["issuer_id"] for row in issuer_rows}
        filing_ids: dict[str, uuid.UUID] = {}
        changed_filings = 0
        for filing in sec_result.filings:
            issuer_id = issuer_ids.get(filing.cik)
            if issuer_id is None:
                continue
            filing_id = _stable_uuid("sec-filing", filing.accession)
            inserted = connection.execute(
                """
                INSERT INTO fundamental.sec_filing(
                    filing_id, issuer_id, accession_no, form_type, period_end,
                    filed_date, accepted_at, primary_document_url,
                    is_amendment, source_snapshot_id
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (accession_no) DO NOTHING
                RETURNING filing_id
                """,
                (
                    filing_id,
                    issuer_id,
                    filing.accession,
                    filing.form,
                    filing.period,
                    filing.filed,
                    filing.accepted_at,
                    filing.primary_document_url,
                    filing.amendment,
                    filing_snapshot_id,
                ),
            ).fetchone()
            if inserted is not None:
                changed_filings += 1
                filing_id = inserted["filing_id"]
            else:
                existing = connection.execute(
                    "SELECT filing_id FROM fundamental.sec_filing WHERE accession_no = %s",
                    (filing.accession,),
                ).fetchone()
                if existing is None:
                    raise RuntimeError("Could not resolve SEC filing")
                filing_id = existing["filing_id"]
            filing_ids[filing.accession] = filing_id
            connection.execute(
                """
                INSERT INTO fundamental.sec_filing_observation(
                    source_snapshot_id, filing_id, observed_at
                )
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (filing_snapshot_id, filing_id, observed_at),
            )
        changed_facts = 0
        for fact in sec_result.facts:
            issuer_id = issuer_ids.get(fact.cik)
            filing_id = filing_ids.get(fact.accession)
            if issuer_id is None or filing_id is None:
                continue
            fact_id = _stable_uuid("sec-fact", fact.context_hash)
            inserted = connection.execute(
                """
                INSERT INTO fundamental.fact(
                    fact_id, filing_id, issuer_id, taxonomy, concept, unit,
                    period_start, period_end, value_numeric, decimals,
                    fiscal_year, fiscal_period, frame, context_hash,
                    source_snapshot_id, source_available_at, observed_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
                ON CONFLICT (context_hash) DO NOTHING
                RETURNING fact_id
                """,
                (
                    fact_id,
                    filing_id,
                    issuer_id,
                    fact.taxonomy,
                    fact.concept,
                    fact.unit,
                    fact.period_start,
                    fact.period_end,
                    fact.value,
                    fact.decimals,
                    fact.fy,
                    fact.fp,
                    fact.frame,
                    fact.context_hash,
                    fact_snapshot_id,
                    fact.accepted_at,
                    observed_at,
                ),
            ).fetchone()
            if inserted is not None:
                changed_facts += 1
                fact_id = inserted["fact_id"]
            connection.execute(
                """
                INSERT INTO fundamental.fact_observation(
                    source_snapshot_id, fact_id, observed_at
                )
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (fact_snapshot_id, fact_id, observed_at),
            )
        snapshots = self._manifest_snapshot_ids(connection, result.input_manifest_id)
        snapshots.update(
            {
                "sec_filings_backfill_derived": filing_snapshot_id,
                "sec_facts_backfill_derived": fact_snapshot_id,
            }
        )
        manifest_id, context_id = ProductionRepository._persist_manifest(
            connection,
            run_spec,
            _canonical_hash(
                {
                    "pipeline": "maximum_data_backfill_with_sec",
                    "date": run_spec.target_date.isoformat(),
                }
            ),
            snapshots,
            raw_objects,
        )
        return BackfillDateResult(
            **{
                **result.__dict__,
                "input_manifest_id": manifest_id,
                "execution_context_id": context_id,
                "changed_filings": changed_filings,
                "changed_facts": changed_facts,
                "collected_filings": len(sec_result.filings),
                "collected_facts": len(sec_result.facts),
            }
        )

    def persist_massive_supplements(
        self,
        *,
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        result: BackfillDateResult,
        actions: tuple[CorporateAction, ...],
        news: tuple[NewsItem, ...],
        raw_objects: dict[str, RawObject],
        observed_at: datetime,
        parent_snapshot_ids: dict[str, uuid.UUID],
    ) -> BackfillDateResult:
        massive_source_id = Database._upsert_source(
            connection,
            "MASSIVE_STOCKS",
            "Massive Stocks API",
            "https://api.massive.com",
            "PROVIDER_TERMS_REQUIRED",
        )
        dividend_snapshot_id = self._persist_derived_snapshot(
            connection=connection,
            run_spec=run_spec,
            run_id=result.ingestion_run_id,
            source_id=massive_source_id,
            dataset_code="massive_dividends_backfill_derived",
            raw=raw_objects["massive_dividends_backfill_derived"],
            observed_at=observed_at,
            parent_snapshot_id=parent_snapshot_ids["massive_dividends_backfill"],
        )
        split_snapshot_id = self._persist_derived_snapshot(
            connection=connection,
            run_spec=run_spec,
            run_id=result.ingestion_run_id,
            source_id=massive_source_id,
            dataset_code="massive_splits_backfill_derived",
            raw=raw_objects["massive_splits_backfill_derived"],
            observed_at=observed_at,
            parent_snapshot_id=parent_snapshot_ids["massive_splits_backfill"],
        )
        news_snapshot_id = self._persist_derived_snapshot(
            connection=connection,
            run_spec=run_spec,
            run_id=result.ingestion_run_id,
            source_id=massive_source_id,
            dataset_code="massive_news_backfill_derived",
            raw=raw_objects["massive_news_backfill_derived"],
            observed_at=observed_at,
            parent_snapshot_id=parent_snapshot_ids["massive_news_backfill"],
        )
        instrument_rows = connection.execute(
            """
            SELECT symbol, instrument_id
            FROM ref.universe_member
            WHERE universe_version_id = %s
            """,
            (result.universe_version_id,),
        ).fetchall()
        instrument_ids = {str(row["symbol"]): row["instrument_id"] for row in instrument_rows}
        changed_actions = ProductionRepository._persist_actions(
            connection,
            actions,
            instrument_ids,
            massive_source_id,
            {
                "massive_dividends": dividend_snapshot_id,
                "massive_splits": split_snapshot_id,
            },
            observed_at,
        )
        changed_events = ProductionRepository(self.database)._persist_news(
            connection,
            news,
            instrument_ids,
            massive_source_id,
            news_snapshot_id,
            observed_at,
        )
        snapshots = {
            "sp500_universe_backfill": result.universe_snapshot_id,
            "massive_grouped_daily_backfill": result.market_snapshot_id,
            "massive_dividends_backfill_derived": dividend_snapshot_id,
            "massive_splits_backfill_derived": split_snapshot_id,
            "massive_news_backfill_derived": news_snapshot_id,
        }
        manifest_id, context_id = ProductionRepository._persist_manifest(
            connection,
            run_spec,
            _canonical_hash(
                {
                    "pipeline": "maximum_data_backfill",
                    "date": run_spec.target_date.isoformat(),
                }
            ),
            snapshots,
            raw_objects,
        )
        return BackfillDateResult(
            ingestion_run_id=result.ingestion_run_id,
            input_manifest_id=manifest_id,
            execution_context_id=context_id,
            universe_version_id=result.universe_version_id,
            universe_count=result.universe_count,
            collected_bars=result.collected_bars,
            changed_bars=result.changed_bars,
            missing_bars=result.missing_bars,
            universe_snapshot_id=result.universe_snapshot_id,
            market_snapshot_id=result.market_snapshot_id,
            changed_actions=changed_actions,
            changed_events=changed_events,
            collected_actions=len(actions),
            collected_events=len(news),
        )

    @staticmethod
    def _persist_derived_snapshot(
        *,
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        run_id: uuid.UUID,
        source_id: int,
        dataset_code: str,
        raw: RawObject,
        observed_at: datetime,
        parent_snapshot_id: uuid.UUID,
    ) -> uuid.UUID:
        snapshot_id = Database._upsert_snapshot(
            connection=connection,
            run_id=run_id,
            source_id=source_id,
            dataset_code=dataset_code,
            target_date=run_spec.target_date,
            as_of_at=run_spec.cutoff_at,
            fetched_at=observed_at,
            source_available_at=run_spec.cutoff_at,
            availability_basis="DERIVED_SOURCE_AVAILABLE_AT_FILTER",
            raw=raw,
            is_reconstruction=True,
        )
        connection.execute(
            """
            UPDATE ops.source_snapshot
               SET snapshot_kind = 'DELTA',
                   parent_snapshot_id = %s
             WHERE source_snapshot_id = %s
            """,
            (parent_snapshot_id, snapshot_id),
        )
        return snapshot_id

    @staticmethod
    def _manifest_snapshot_ids(
        connection: Connection[dict[str, object]],
        manifest_id: uuid.UUID,
    ) -> dict[str, uuid.UUID]:
        rows = connection.execute(
            """
            SELECT dataset_code, source_snapshot_id
            FROM ops.input_manifest_member
            WHERE input_manifest_id = %s
            """,
            (manifest_id,),
        ).fetchall()
        return {str(row["dataset_code"]): row["source_snapshot_id"] for row in rows}

    @staticmethod
    def _start_run(
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        run_key: str,
        requested_count: int,
    ) -> uuid.UUID:
        existing = connection.execute(
            """
            SELECT ingestion_run_id
            FROM ops.ingestion_run
            WHERE dataset_code = 'massive_price_backfill'
              AND target_date = %s
              AND config_hash = %s
            """,
            (run_spec.target_date, run_key),
        ).fetchone()
        if existing is not None:
            run_id = existing["ingestion_run_id"]
            connection.execute(
                """
                UPDATE ops.ingestion_run
                   SET status = 'RUNNING',
                       requested_count = %s,
                       received_count = 0,
                       inserted_count = 0,
                       error_count = 0,
                       error_message = NULL,
                       started_at = now(),
                       finished_at = NULL
                 WHERE ingestion_run_id = %s
                """,
                (requested_count, run_id),
            )
            return run_id
        run_id = uuid.uuid4()
        connection.execute(
            """
            INSERT INTO ops.ingestion_run(
                ingestion_run_id, dataset_code, target_date, cutoff_at,
                knowledge_mode, config_hash, status, requested_count
            )
            VALUES (
                %s, 'massive_price_backfill', %s, %s,
                'HISTORICAL_RECONSTRUCTION', %s, 'RUNNING', %s
            )
            """,
            (
                run_id,
                run_spec.target_date,
                run_spec.cutoff_at,
                run_key,
                requested_count,
            ),
        )
        return run_id
