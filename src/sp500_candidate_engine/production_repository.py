from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from datetime import datetime, time, timedelta

from psycopg import Connection

from sp500_candidate_engine import __version__
from sp500_candidate_engine.database import (
    Database,
    _canonical_hash,
    _price,
    _run_config_hash,
    _stable_uuid,
)
from sp500_candidate_engine.models import (
    NEW_YORK,
    UTC,
    KnowledgeMode,
    RunSpec,
    UniverseCollection,
)
from sp500_candidate_engine.production_models import (
    AlphaEarningsCollection,
    CorporateAction,
    EarningsEvent,
    MassiveCollection,
    NewsItem,
    SecReferenceCollection,
)
from sp500_candidate_engine.raw_store import RawObject


@dataclass(frozen=True)
class ProductionPersistedRun:
    ingestion_run_id: uuid.UUID
    input_manifest_id: uuid.UUID
    execution_context_id: uuid.UUID
    universe_version_id: uuid.UUID
    universe_count: int
    changed_bars: int
    changed_actions: int
    changed_events: int
    missing_bars: int


def resolve_revision(
    *,
    current_revision: int | None,
    current_hash: str | None,
    new_hash: str,
) -> tuple[int, bool]:
    if current_revision is not None and current_hash == new_hash:
        return current_revision, False
    return (current_revision + 1 if current_revision is not None else 1), True


class ProductionRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    def persist(
        self,
        *,
        run_spec: RunSpec,
        config_hash: str,
        universe: UniverseCollection,
        massive: MassiveCollection,
        sec: SecReferenceCollection,
        alpha: AlphaEarningsCollection,
        raw_objects: dict[str, RawObject],
    ) -> ProductionPersistedRun:
        run_key = _run_config_hash(config_hash, run_spec.knowledge_mode)
        with self.database.connect() as connection, connection.transaction():
            run_id = self._start_run(connection, run_spec, run_key, len(universe.members))
            source_ids = {
                "universe": Database._upsert_source(
                    connection,
                    "WIKIPEDIA_REVISION",
                    "Wikipedia revision API",
                    "https://en.wikipedia.org/w/api.php",
                    "PUBLIC_REFERENCE",
                ),
                "massive": Database._upsert_source(
                    connection,
                    "MASSIVE_STOCKS",
                    "Massive Stocks API",
                    "https://api.massive.com",
                    "PROVIDER_TERMS_REQUIRED",
                ),
                "sec": Database._upsert_source(
                    connection,
                    "SEC_EDGAR",
                    "SEC EDGAR",
                    "https://data.sec.gov",
                    "PUBLIC_GOVERNMENT_DATA",
                ),
                "alpha": Database._upsert_source(
                    connection,
                    "ALPHA_VANTAGE",
                    "Alpha Vantage",
                    "https://www.alphavantage.co",
                    "PROVIDER_TERMS_REQUIRED",
                ),
            }
            snapshots = self._persist_snapshots(
                connection,
                run_id,
                run_spec,
                universe,
                massive,
                sec,
                alpha,
                source_ids,
                raw_objects,
            )
            universe_version_id, instrument_ids = Database._persist_universe(
                connection,
                run_spec,
                universe,
                snapshots["sp500_universe"],
            )
            self._persist_sec_reference(
                connection,
                run_spec,
                sec,
                snapshots["sec_company_tickers"],
                instrument_ids,
            )
            changed_bars = Database._persist_bars(
                connection,
                massive.bars,
                instrument_ids,
                source_ids["massive"],
                snapshots["massive_grouped_daily"],
                massive.source_available_at,
                massive.observed_at,
            )
            missing_symbols = sorted(set(instrument_ids) - {bar.symbol for bar in massive.bars})
            self._persist_missing_bar_issues(
                connection,
                run_id,
                missing_symbols,
            )
            changed_actions = self._persist_actions(
                connection,
                massive.actions,
                instrument_ids,
                source_ids["massive"],
                snapshots,
                massive.observed_at,
            )
            changed_events = self._persist_news(
                connection,
                massive.news,
                instrument_ids,
                source_ids["massive"],
                snapshots["massive_news"],
                massive.observed_at,
            )
            changed_events += self._persist_earnings(
                connection,
                alpha.events,
                instrument_ids,
                source_ids["alpha"],
                snapshots["alpha_earnings"],
                alpha.observed_at,
            )
            manifest_id, context_id = self._persist_manifest(
                connection,
                run_spec,
                run_key,
                snapshots,
                raw_objects,
            )
            connection.execute(
                """
                UPDATE ops.ingestion_run
                   SET status = 'SUCCEEDED',
                       received_count = %s,
                       inserted_count = %s,
                       error_count = %s,
                       finished_at = now()
                 WHERE ingestion_run_id = %s
                """,
                (
                    len(massive.bars),
                    changed_bars + changed_actions + changed_events,
                    len(missing_symbols),
                    run_id,
                ),
            )
            return ProductionPersistedRun(
                ingestion_run_id=run_id,
                input_manifest_id=manifest_id,
                execution_context_id=context_id,
                universe_version_id=universe_version_id,
                universe_count=len(universe.members),
                changed_bars=changed_bars,
                changed_actions=changed_actions,
                changed_events=changed_events,
                missing_bars=len(missing_symbols),
            )

    @staticmethod
    def _persist_missing_bar_issues(
        connection: Connection[dict[str, object]],
        run_id: uuid.UUID,
        missing_symbols: list[str],
        dataset_code: str = "massive_grouped_daily",
    ) -> None:
        connection.execute(
            """
            UPDATE ops.data_quality_issue
               SET status = 'RESOLVED',
                   resolved_at = now()
             WHERE ingestion_run_id = %s
               AND dataset_code = %s
               AND rule_code = 'PROVIDER_BAR_MISSING'
               AND entity_key <> ALL(%s::text[])
               AND status = 'ACTIVE'
            """,
            (run_id, dataset_code, missing_symbols),
        )
        for symbol in missing_symbols:
            updated = connection.execute(
                """
                UPDATE ops.data_quality_issue
                   SET status = 'ACTIVE',
                       details = %s,
                       last_seen_at = now(),
                       resolved_at = NULL
                 WHERE ingestion_run_id = %s
                   AND dataset_code = %s
                   AND entity_key = %s
                   AND rule_code = 'PROVIDER_BAR_MISSING'
                """,
                (
                    json.dumps({"message": "No grouped daily bar returned"}),
                    run_id,
                    dataset_code,
                    symbol,
                ),
            ).rowcount
            if updated:
                continue
            connection.execute(
                """
                INSERT INTO ops.data_quality_issue(
                    issue_id, ingestion_run_id, dataset_code, entity_key,
                    rule_code, severity, details, status, last_seen_at
                )
                VALUES (
                    %s, %s, %s, %s,
                    'PROVIDER_BAR_MISSING', 'WARNING', %s, 'ACTIVE', now()
                )
                ON CONFLICT DO NOTHING
                """,
                (
                    uuid.uuid4(),
                    run_id,
                    dataset_code,
                    symbol,
                    json.dumps({"message": "No grouped daily bar returned"}),
                ),
            )

    @staticmethod
    def _start_run(
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        run_key: str,
        requested_count: int,
    ) -> uuid.UUID:
        existing = connection.execute(
            """
            SELECT ingestion_run_id, status
            FROM ops.ingestion_run
            WHERE dataset_code = 'production_daily_input'
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
                       cutoff_at = %s,
                       requested_count = %s,
                       received_count = 0,
                       inserted_count = 0,
                       error_count = 0,
                       error_message = NULL,
                       started_at = now(),
                       finished_at = NULL
                 WHERE ingestion_run_id = %s
                """,
                (run_spec.cutoff_at, requested_count, run_id),
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
                %s, 'production_daily_input', %s, %s,
                %s, %s, 'RUNNING', %s
            )
            """,
            (
                run_id,
                run_spec.target_date,
                run_spec.cutoff_at,
                run_spec.knowledge_mode.value,
                run_key,
                requested_count,
            ),
        )
        return run_id

    def _persist_snapshots(
        self,
        connection: Connection[dict[str, object]],
        run_id: uuid.UUID,
        run_spec: RunSpec,
        universe: UniverseCollection,
        massive: MassiveCollection,
        sec: SecReferenceCollection,
        alpha: AlphaEarningsCollection,
        source_ids: dict[str, int],
        raw_objects: dict[str, RawObject],
    ) -> dict[str, uuid.UUID]:
        specs = {
            "sp500_universe": (
                source_ids["universe"],
                universe.revision_at,
                universe.observed_at,
                universe.revision_at,
                "WIKIPEDIA_REVISION_TIMESTAMP",
            ),
            "massive_grouped_daily": (
                source_ids["massive"],
                run_spec.cutoff_at,
                massive.observed_at,
                massive.source_available_at,
                "ASSUMED_16_15_AMERICA_NEW_YORK",
            ),
            "massive_dividends": (
                source_ids["massive"],
                run_spec.cutoff_at,
                massive.observed_at,
                massive.observed_at,
                "OBSERVED_AT",
            ),
            "massive_splits": (
                source_ids["massive"],
                run_spec.cutoff_at,
                massive.observed_at,
                massive.observed_at,
                "OBSERVED_AT",
            ),
            "massive_news": (
                source_ids["massive"],
                run_spec.cutoff_at,
                massive.observed_at,
                massive.observed_at,
                "OBSERVED_AT",
            ),
            "sec_company_tickers": (
                source_ids["sec"],
                run_spec.cutoff_at,
                sec.observed_at,
                sec.observed_at,
                "OBSERVED_AT",
            ),
            "alpha_earnings": (
                source_ids["alpha"],
                run_spec.cutoff_at,
                alpha.observed_at,
                alpha.observed_at,
                "OBSERVED_AT",
            ),
        }
        snapshots: dict[str, uuid.UUID] = {}
        for dataset, (
            source_id,
            as_of_at,
            fetched_at,
            source_available_at,
            availability_basis,
        ) in specs.items():
            snapshots[dataset] = Database._upsert_snapshot(
                connection=connection,
                run_id=run_id,
                source_id=source_id,
                dataset_code=dataset,
                target_date=run_spec.target_date,
                as_of_at=as_of_at,
                fetched_at=fetched_at,
                source_available_at=source_available_at,
                availability_basis=availability_basis,
                raw=raw_objects[dataset],
                is_reconstruction=(
                    run_spec.knowledge_mode is KnowledgeMode.HISTORICAL_RECONSTRUCTION
                ),
            )
        return snapshots

    @staticmethod
    def _persist_sec_reference(
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        sec: SecReferenceCollection,
        snapshot_id: uuid.UUID,
        instrument_ids: dict[str, uuid.UUID],
    ) -> None:
        companies = {company.ticker.replace(".", "-"): company for company in sec.companies}
        for provider_symbol, instrument_id in (
            (symbol.replace(".", "-"), instrument_id)
            for symbol, instrument_id in instrument_ids.items()
        ):
            company = companies.get(provider_symbol)
            if company is None:
                continue
            connection.execute(
                """
                UPDATE ref.issuer issuer
                   SET cik = COALESCE(issuer.cik, %s),
                       legal_name = %s
                  FROM ref.instrument instrument
                 WHERE instrument.instrument_id = %s
                   AND issuer.issuer_id = instrument.issuer_id
                """,
                (company.cik, company.name, instrument_id),
            )
            current = connection.execute(
                """
                SELECT instrument_state_id, revision_no, primary_exchange, status
                FROM ref.instrument_state
                WHERE instrument_id = %s
                ORDER BY valid_from DESC, revision_no DESC
                LIMIT 1
                """,
                (instrument_id,),
            ).fetchone()
            values = (company.exchange, "LISTED")
            if (
                current is not None
                and (
                    current["primary_exchange"],
                    current["status"],
                )
                == values
            ):
                continue
            revision = int(current["revision_no"]) + 1 if current else 1
            if current is not None:
                connection.execute(
                    """
                    UPDATE ref.instrument_state
                       SET valid_to = %s
                     WHERE instrument_state_id = %s
                       AND valid_to IS NULL
                       AND valid_from < %s
                    """,
                    (
                        run_spec.target_date - timedelta(days=1),
                        current["instrument_state_id"],
                        run_spec.target_date,
                    ),
                )
            state_id = _stable_uuid(
                "instrument-state",
                f"{instrument_id}:{run_spec.target_date}:{revision}",
            )
            connection.execute(
                """
                INSERT INTO ref.instrument_state(
                    instrument_state_id, instrument_id, primary_exchange,
                    status, valid_from, source_available_at, observed_at,
                    source_snapshot_id, revision_no
                )
                VALUES (%s, %s, %s, 'LISTED', %s, %s, %s, %s, %s)
                """,
                (
                    state_id,
                    instrument_id,
                    company.exchange,
                    run_spec.target_date,
                    sec.observed_at,
                    sec.observed_at,
                    snapshot_id,
                    revision,
                ),
            )

    @staticmethod
    def _persist_actions(
        connection: Connection[dict[str, object]],
        actions: tuple[CorporateAction, ...],
        instrument_ids: dict[str, uuid.UUID],
        source_id: int,
        snapshots: dict[str, uuid.UUID],
        observed_at: datetime,
    ) -> int:
        changed = 0
        for action in actions:
            instrument_id = instrument_ids.get(action.symbol)
            if instrument_id is None:
                continue
            payload_hash = _canonical_hash(action.metadata)
            current = connection.execute(
                """
                SELECT action_id, revision_no, payload_hash
                FROM market.corporate_action
                WHERE source_id = %s AND source_action_id = %s
                ORDER BY revision_no DESC
                LIMIT 1
                """,
                (source_id, action.provider_action_id),
            ).fetchone()
            revision, is_changed = resolve_revision(
                current_revision=int(current["revision_no"]) if current else None,
                current_hash=str(current["payload_hash"]) if current else None,
                new_hash=payload_hash,
            )
            if not is_changed:
                assert current is not None
                action_id = current["action_id"]
            else:
                action_id = _stable_uuid(
                    "corporate-action",
                    f"{source_id}:{action.provider_action_id}:{revision}",
                )
                snapshot_id = snapshots[
                    "massive_dividends" if action.action_type == "DIVIDEND" else "massive_splits"
                ]
                connection.execute(
                    """
                    INSERT INTO market.corporate_action(
                        action_id, instrument_id, source_id, source_action_id,
                        action_type, revision_no, effective_date, declaration_date,
                        record_date, pay_date, cash_amount, currency, split_from,
                        split_to, source_available_at, observed_at,
                        origin_snapshot_id, payload_hash, metadata
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        action_id,
                        instrument_id,
                        source_id,
                        action.provider_action_id,
                        action.action_type,
                        revision,
                        action.effective_date,
                        action.declaration_date,
                        action.record_date,
                        action.pay_date,
                        _price(action.cash_amount),
                        action.currency,
                        _price(action.split_from),
                        _price(action.split_to),
                        action.source_available_at,
                        observed_at,
                        snapshot_id,
                        payload_hash,
                        json.dumps(action.metadata),
                    ),
                )
                changed += 1
            snapshot_id = snapshots[
                "massive_dividends" if action.action_type == "DIVIDEND" else "massive_splits"
            ]
            connection.execute(
                """
                INSERT INTO market.corporate_action_observation(
                    source_snapshot_id, action_id, observed_at
                )
                VALUES (%s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (snapshot_id, action_id, observed_at),
            )
        return changed

    def _persist_news(
        self,
        connection: Connection[dict[str, object]],
        news_items: tuple[NewsItem, ...],
        instrument_ids: dict[str, uuid.UUID],
        source_id: int,
        snapshot_id: uuid.UUID,
        observed_at: datetime,
    ) -> int:
        changed = 0
        for item in news_items:
            changed += self._persist_event(
                connection,
                source_id=source_id,
                source_event_id=item.provider_event_id,
                event_type="NEWS",
                canonical_key=f"NEWS:{item.provider_event_id}",
                title=item.title,
                source_url=item.article_url,
                scheduled_at=None,
                published_at=item.published_at,
                source_available_at=item.published_at,
                observed_at=observed_at,
                snapshot_id=snapshot_id,
                metadata=item.metadata,
                symbols=item.tickers,
                instrument_ids=instrument_ids,
            )
        return changed

    def _persist_earnings(
        self,
        connection: Connection[dict[str, object]],
        events: tuple[EarningsEvent, ...],
        instrument_ids: dict[str, uuid.UUID],
        source_id: int,
        snapshot_id: uuid.UUID,
        observed_at: datetime,
    ) -> int:
        changed = 0
        for item in events:
            instrument_id = instrument_ids.get(item.symbol)
            if instrument_id is None:
                continue
            event_time = {
                "bmo": time(hour=8),
                "amc": time(hour=16, minute=30),
            }.get((item.time_of_day or "").lower(), time(hour=12))
            scheduled_at = datetime.combine(
                item.report_date, event_time, tzinfo=NEW_YORK
            ).astimezone(UTC)
            fiscal_key = item.fiscal_date_ending or item.report_date
            changed += self._persist_event(
                connection,
                source_id=source_id,
                source_event_id=f"EARNINGS:{item.symbol}:{fiscal_key.isoformat()}",
                event_type="EARNINGS",
                canonical_key=f"EARNINGS:{item.symbol}:{fiscal_key.isoformat()}",
                title=f"{item.symbol} earnings",
                source_url=None,
                scheduled_at=scheduled_at,
                published_at=None,
                source_available_at=observed_at,
                observed_at=observed_at,
                snapshot_id=snapshot_id,
                metadata={
                    "company_name": item.company_name,
                    "report_date": item.report_date.isoformat(),
                    "fiscal_date_ending": (
                        item.fiscal_date_ending.isoformat() if item.fiscal_date_ending else None
                    ),
                    "estimate": item.estimate,
                    "currency": item.currency,
                    "time_of_day": item.time_of_day,
                },
                symbols=(item.symbol,),
                instrument_ids=instrument_ids,
            )
        return changed

    @staticmethod
    def _persist_event(
        connection: Connection[dict[str, object]],
        *,
        source_id: int,
        source_event_id: str,
        event_type: str,
        canonical_key: str,
        title: str,
        source_url: str | None,
        scheduled_at: datetime | None,
        published_at: datetime | None,
        source_available_at: datetime,
        observed_at: datetime,
        snapshot_id: uuid.UUID,
        metadata: dict[str, object],
        symbols: tuple[str, ...],
        instrument_ids: dict[str, uuid.UUID],
    ) -> int:
        event_id = _stable_uuid("market-event", f"{source_id}:{source_event_id}")
        connection.execute(
            """
            INSERT INTO event.market_event(
                event_id, source_id, source_event_id, event_type, canonical_key
            )
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (event_id) DO NOTHING
            """,
            (event_id, source_id, source_event_id, event_type, canonical_key),
        )
        payload_hash = _canonical_hash(metadata)
        current = connection.execute(
            """
            SELECT event_revision_id, revision_no, payload_hash
            FROM event.event_revision
            WHERE event_id = %s
            ORDER BY revision_no DESC
            LIMIT 1
            """,
            (event_id,),
        ).fetchone()
        changed = 0
        revision, is_changed = resolve_revision(
            current_revision=int(current["revision_no"]) if current else None,
            current_hash=str(current["payload_hash"]) if current else None,
            new_hash=payload_hash,
        )
        if not is_changed:
            assert current is not None
            revision_id = current["event_revision_id"]
        else:
            revision_id = _stable_uuid("event-revision", f"{event_id}:{revision}")
            connection.execute(
                """
                INSERT INTO event.event_revision(
                    event_revision_id, event_id, revision_no, title,
                    source_url, status, scheduled_at, published_at,
                    source_available_at, observed_at, origin_snapshot_id,
                    payload_hash, metadata
                )
                VALUES (
                    %s, %s, %s, %s, %s, 'ACTIVE', %s, %s,
                    %s, %s, %s, %s, %s
                )
                """,
                (
                    revision_id,
                    event_id,
                    revision,
                    title,
                    source_url,
                    scheduled_at,
                    published_at,
                    source_available_at,
                    observed_at,
                    snapshot_id,
                    payload_hash,
                    json.dumps(metadata),
                ),
            )
            changed = 1
        connection.execute(
            """
            INSERT INTO event.event_revision_observation(
                source_snapshot_id, event_revision_id, observed_at
            )
            VALUES (%s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (snapshot_id, revision_id, observed_at),
        )
        for symbol in symbols:
            instrument_id = instrument_ids.get(symbol)
            if instrument_id is None:
                continue
            connection.execute(
                """
                INSERT INTO event.event_instrument(event_id, instrument_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                """,
                (event_id, instrument_id),
            )
        return changed

    @staticmethod
    def _persist_manifest(
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        run_key: str,
        snapshots: dict[str, uuid.UUID],
        raw_objects: dict[str, RawObject],
    ) -> tuple[uuid.UUID, uuid.UUID]:
        manifest_rows = [
            {
                "dataset_code": dataset,
                "source_snapshot_id": str(snapshot_id),
                "content_hash": raw_objects[dataset].content_hash,
                "precedence": 0,
            }
            for dataset, snapshot_id in sorted(snapshots.items())
        ]
        manifest_hash = _canonical_hash(manifest_rows)
        manifest_id = _stable_uuid("input-manifest", manifest_hash)
        connection.execute(
            """
            INSERT INTO ops.input_manifest(input_manifest_id, manifest_hash)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
            """,
            (manifest_id, manifest_hash),
        )
        for row in manifest_rows:
            connection.execute(
                """
                INSERT INTO ops.input_manifest_member(
                    input_manifest_id, source_snapshot_id, dataset_code,
                    precedence, lineage_role
                )
                VALUES (%s, %s, %s, 0, 'SINGLE')
                ON CONFLICT DO NOTHING
                """,
                (
                    manifest_id,
                    uuid.UUID(row["source_snapshot_id"]),
                    row["dataset_code"],
                ),
            )
        context_hash = _canonical_hash(
            {
                "manifest_hash": manifest_hash,
                "cutoff_at": run_spec.cutoff_at.isoformat(),
                "knowledge_mode": run_spec.knowledge_mode.value,
                "code_version": __version__,
                "config_version": run_key,
            }
        )
        context_id = _stable_uuid("execution-context", context_hash)
        connection.execute(
            """
            INSERT INTO ops.execution_context(
                execution_context_id, input_manifest_id, cutoff_at,
                knowledge_mode, code_version, config_version, context_hash
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT DO NOTHING
            """,
            (
                context_id,
                manifest_id,
                run_spec.cutoff_at,
                run_spec.knowledge_mode.value,
                __version__,
                run_key,
                context_hash,
            ),
        )
        return manifest_id, context_id
