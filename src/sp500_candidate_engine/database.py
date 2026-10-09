from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Generator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from pathlib import Path

import psycopg
from azure.identity import AzureCliCredential, DefaultAzureCredential
from psycopg import Connection
from psycopg.rows import dict_row

from sp500_candidate_engine import __version__
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.models import (
    DailyBar,
    KnowledgeMode,
    MarketCollection,
    RunSpec,
    UniverseCollection,
)
from sp500_candidate_engine.raw_store import RawObject

POSTGRES_SCOPE = "https://ossrdbms-aad.database.windows.net/.default"
UUID_NAMESPACE = uuid.UUID("cd84b949-9486-4e7e-8ed3-834d221740f7")


def _canonical_hash(payload: object) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(encoded).hexdigest()


def _stable_uuid(kind: str, value: str) -> uuid.UUID:
    return uuid.uuid5(UUID_NAMESPACE, f"{kind}:{value}")


def _price(value: float | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value)).quantize(Decimal("0.00000001"), rounding=ROUND_HALF_UP)


def _run_config_hash(base_config_hash: str, mode: KnowledgeMode) -> str:
    return _canonical_hash(
        {
            "base_config_hash": base_config_hash,
            "knowledge_mode": mode.value,
            "collector_version": __version__,
        }
    )


@dataclass(frozen=True)
class PersistedRun:
    ingestion_run_id: uuid.UUID
    input_manifest_id: uuid.UUID
    execution_context_id: uuid.UUID
    universe_version_id: uuid.UUID
    universe_count: int
    bar_count: int
    failure_count: int
    already_existed: bool = False


class Database:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        if settings.azure_credential_mode == "azure_cli":
            self.credential = AzureCliCredential(
                tenant_id=settings.azure_tenant_id,
                process_timeout=settings.pg_connect_timeout,
            )
        else:
            self.credential = DefaultAzureCredential()

    @contextmanager
    def connect(
        self, *, autocommit: bool = False
    ) -> Generator[Connection[dict[str, object]], None, None]:
        token = self.credential.get_token(POSTGRES_SCOPE).token
        with psycopg.connect(
            host=self.settings.pg_host,
            port=self.settings.pg_port,
            dbname=self.settings.pg_database,
            user=self.settings.pg_user,
            password=token,
            sslmode=self.settings.pg_sslmode,
            connect_timeout=self.settings.pg_connect_timeout,
            autocommit=autocommit,
            row_factory=dict_row,
        ) as connection:
            yield connection

    def migrate(self) -> None:
        migration_dir = Path(__file__).parents[2] / "sql"
        with self.connect() as connection, connection.transaction():
            for migration_path in sorted(migration_dir.glob("*.sql")):
                connection.execute(migration_path.read_text(encoding="utf-8"))

    def persist_collection(
        self,
        *,
        run_spec: RunSpec,
        config_hash: str,
        universe: UniverseCollection,
        market: MarketCollection,
        universe_raw: RawObject,
        market_raw: RawObject,
    ) -> PersistedRun:
        run_key = _run_config_hash(config_hash, run_spec.knowledge_mode)
        with self.connect() as connection, connection.transaction():
            existing = connection.execute(
                """
                SELECT ingestion_run_id, status, received_count, inserted_count, error_count
                FROM ops.ingestion_run
                WHERE dataset_code = %s AND target_date = %s AND config_hash = %s
                """,
                ("daily_candidate_input", run_spec.target_date, run_key),
            ).fetchone()
            if existing is not None:
                if existing["status"] != "SUCCEEDED":
                    raise RuntimeError(
                        f"Existing ingestion run is not reusable: {existing['status']}"
                    )
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
                    (len(universe.members), run_id),
                )
                already_existed = True
            else:
                run_id = uuid.uuid4()
                connection.execute(
                    """
                    INSERT INTO ops.ingestion_run(
                        ingestion_run_id, dataset_code, target_date, cutoff_at,
                        knowledge_mode, config_hash, status, requested_count
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, 'RUNNING', %s)
                    """,
                    (
                        run_id,
                        "daily_candidate_input",
                        run_spec.target_date,
                        run_spec.cutoff_at,
                        run_spec.knowledge_mode.value,
                        run_key,
                        len(universe.members),
                    ),
                )
                already_existed = False
            wiki_source_id = self._upsert_source(
                connection,
                "WIKIPEDIA_REVISION",
                "Wikipedia revision API",
                "https://en.wikipedia.org/w/api.php",
                "PUBLIC_REFERENCE",
            )
            yahoo_source_id = self._upsert_source(
                connection,
                "YAHOO_CHART",
                "Yahoo chart API",
                "https://query1.finance.yahoo.com",
                "PROVIDER_TERMS_REQUIRED",
            )
            universe_snapshot_id = self._upsert_snapshot(
                connection=connection,
                run_id=run_id,
                source_id=wiki_source_id,
                dataset_code="sp500_universe",
                target_date=run_spec.target_date,
                as_of_at=universe.revision_at,
                fetched_at=universe.observed_at,
                source_available_at=universe.revision_at,
                availability_basis="WIKIPEDIA_REVISION_TIMESTAMP",
                raw=universe_raw,
                is_reconstruction=(
                    run_spec.knowledge_mode is KnowledgeMode.HISTORICAL_RECONSTRUCTION
                ),
            )
            market_snapshot_id = self._upsert_snapshot(
                connection=connection,
                run_id=run_id,
                source_id=yahoo_source_id,
                dataset_code="daily_bar",
                target_date=run_spec.target_date,
                as_of_at=run_spec.cutoff_at,
                fetched_at=market.observed_at,
                source_available_at=market.source_available_at,
                availability_basis="ASSUMED_16_15_AMERICA_NEW_YORK",
                raw=market_raw,
                is_reconstruction=(
                    run_spec.knowledge_mode is KnowledgeMode.HISTORICAL_RECONSTRUCTION
                ),
            )
            universe_version_id, instrument_ids = self._persist_universe(
                connection,
                run_spec,
                universe,
                universe_snapshot_id,
            )
            inserted_bars = self._persist_bars(
                connection,
                market.bars,
                instrument_ids,
                yahoo_source_id,
                market_snapshot_id,
                market.source_available_at,
                market.observed_at,
            )
            failure_symbols = sorted(market.failures)
            connection.execute(
                """
                UPDATE ops.data_quality_issue
                   SET status = 'RESOLVED',
                       resolved_at = now()
                 WHERE ingestion_run_id = %s
                   AND dataset_code = 'daily_bar'
                   AND rule_code = 'PROVIDER_FETCH_FAILED'
                   AND entity_key <> ALL(%s::text[])
                   AND status = 'ACTIVE'
                """,
                (run_id, failure_symbols),
            )
            for symbol, message in market.failures.items():
                updated = connection.execute(
                    """
                    UPDATE ops.data_quality_issue
                       SET status = 'ACTIVE',
                           details = %s,
                           last_seen_at = now(),
                           resolved_at = NULL
                     WHERE ingestion_run_id = %s
                       AND dataset_code = 'daily_bar'
                       AND entity_key = %s
                       AND rule_code = 'PROVIDER_FETCH_FAILED'
                    """,
                    (json.dumps({"message": message}), run_id, symbol),
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
                        %s, %s, 'daily_bar', %s, 'PROVIDER_FETCH_FAILED',
                        'WARNING', %s, 'ACTIVE', now()
                    )
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        uuid.uuid4(),
                        run_id,
                        symbol,
                        json.dumps({"message": message}),
                    ),
                )

            manifest_payload = [
                {
                    "dataset_code": "daily_bar",
                    "source_snapshot_id": str(market_snapshot_id),
                    "content_hash": market_raw.content_hash,
                    "precedence": 0,
                },
                {
                    "dataset_code": "sp500_universe",
                    "source_snapshot_id": str(universe_snapshot_id),
                    "content_hash": universe_raw.content_hash,
                    "precedence": 0,
                },
            ]
            manifest_hash = _canonical_hash(
                sorted(manifest_payload, key=lambda item: item["dataset_code"])
            )
            manifest_id = _stable_uuid("input-manifest", manifest_hash)
            connection.execute(
                """
                INSERT INTO ops.input_manifest(input_manifest_id, manifest_hash)
                VALUES (%s, %s)
                ON CONFLICT (input_manifest_id) DO NOTHING
                """,
                (manifest_id, manifest_hash),
            )
            for item in manifest_payload:
                connection.execute(
                    """
                    INSERT INTO ops.input_manifest_member(
                        input_manifest_id, source_snapshot_id, dataset_code,
                        precedence, lineage_role
                    )
                    VALUES (%s, %s, %s, %s, 'SINGLE')
                    ON CONFLICT DO NOTHING
                    """,
                    (
                        manifest_id,
                        uuid.UUID(item["source_snapshot_id"]),
                        item["dataset_code"],
                        item["precedence"],
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
                ON CONFLICT (execution_context_id) DO NOTHING
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
                (len(market.bars), inserted_bars, len(market.failures), run_id),
            )
            return PersistedRun(
                ingestion_run_id=run_id,
                input_manifest_id=manifest_id,
                execution_context_id=context_id,
                universe_version_id=universe_version_id,
                universe_count=len(universe.members),
                bar_count=inserted_bars,
                failure_count=len(market.failures),
                already_existed=already_existed,
            )

    def delete_collection_date(self, target_date: date) -> dict[str, int]:
        counts: dict[str, int] = {}
        with self.connect() as connection, connection.transaction():
            run_rows = connection.execute(
                """
                SELECT ingestion_run_id
                FROM ops.ingestion_run
                WHERE target_date = %s
                """,
                (target_date,),
            ).fetchall()
            run_ids = [row["ingestion_run_id"] for row in run_rows]
            if not run_ids:
                return {
                    "ingestion_runs": 0,
                    "source_snapshots": 0,
                    "daily_bars": 0,
                    "universe_versions": 0,
                }

            snapshot_rows = connection.execute(
                """
                SELECT source_snapshot_id
                FROM ops.source_snapshot
                WHERE ingestion_run_id = ANY(%s)
                """,
                (run_ids,),
            ).fetchall()
            snapshot_ids = [row["source_snapshot_id"] for row in snapshot_rows]
            manifest_ids: list[uuid.UUID] = []
            universe_version_ids: list[uuid.UUID] = []
            if snapshot_ids:
                connection.execute(
                    """
                    DELETE FROM market.daily_bar_observation
                    WHERE source_snapshot_id = ANY(%s)
                    """,
                    (snapshot_ids,),
                )
                manifest_rows = connection.execute(
                    """
                    SELECT DISTINCT input_manifest_id
                    FROM ops.input_manifest_member
                    WHERE source_snapshot_id = ANY(%s)
                    """,
                    (snapshot_ids,),
                ).fetchall()
                manifest_ids = [row["input_manifest_id"] for row in manifest_rows]
                version_rows = connection.execute(
                    """
                    SELECT universe_version_id
                    FROM ref.universe_version
                    WHERE source_snapshot_id = ANY(%s)
                    """,
                    (snapshot_ids,),
                ).fetchall()
                universe_version_ids = [row["universe_version_id"] for row in version_rows]

                counts["daily_bars"] = connection.execute(
                    "DELETE FROM market.daily_bar WHERE source_snapshot_id = ANY(%s)",
                    (snapshot_ids,),
                ).rowcount
                connection.execute(
                    "DELETE FROM ref.instrument_identifier WHERE source_snapshot_id = ANY(%s)",
                    (snapshot_ids,),
                )
            else:
                counts["daily_bars"] = 0

            if universe_version_ids:
                connection.execute(
                    "DELETE FROM ref.universe_member WHERE universe_version_id = ANY(%s)",
                    (universe_version_ids,),
                )
                counts["universe_versions"] = connection.execute(
                    "DELETE FROM ref.universe_version WHERE universe_version_id = ANY(%s)",
                    (universe_version_ids,),
                ).rowcount
            else:
                counts["universe_versions"] = 0

            connection.execute(
                "DELETE FROM ops.data_quality_issue WHERE ingestion_run_id = ANY(%s)",
                (run_ids,),
            )
            if manifest_ids:
                connection.execute(
                    "DELETE FROM ops.execution_context WHERE input_manifest_id = ANY(%s)",
                    (manifest_ids,),
                )
            if snapshot_ids:
                connection.execute(
                    "DELETE FROM ops.input_manifest_member WHERE source_snapshot_id = ANY(%s)",
                    (snapshot_ids,),
                )
            if manifest_ids:
                connection.execute(
                    """
                    DELETE FROM ops.input_manifest im
                    WHERE im.input_manifest_id = ANY(%s)
                      AND NOT EXISTS (
                          SELECT 1
                          FROM ops.input_manifest_member imm
                          WHERE imm.input_manifest_id = im.input_manifest_id
                      )
                    """,
                    (manifest_ids,),
                )
            counts["source_snapshots"] = (
                connection.execute(
                    "DELETE FROM ops.source_snapshot WHERE source_snapshot_id = ANY(%s)",
                    (snapshot_ids,),
                ).rowcount
                if snapshot_ids
                else 0
            )
            counts["ingestion_runs"] = connection.execute(
                "DELETE FROM ops.ingestion_run WHERE ingestion_run_id = ANY(%s)",
                (run_ids,),
            ).rowcount
            connection.execute(
                """
                DELETE FROM ref.instrument i
                WHERE NOT EXISTS (
                    SELECT 1 FROM ref.universe_member um WHERE um.instrument_id = i.instrument_id
                )
                  AND NOT EXISTS (
                    SELECT 1 FROM market.daily_bar db WHERE db.instrument_id = i.instrument_id
                )
                  AND NOT EXISTS (
                    SELECT 1
                    FROM ref.instrument_identifier ii
                    WHERE ii.instrument_id = i.instrument_id
                )
                """
            )
            connection.execute(
                """
                DELETE FROM ref.issuer issuer
                WHERE NOT EXISTS (
                    SELECT 1 FROM ref.instrument i WHERE i.issuer_id = issuer.issuer_id
                )
                """
            )
        return counts

    @staticmethod
    def _upsert_source(
        connection: Connection[dict[str, object]],
        code: str,
        name: str,
        base_url: str,
        license_class: str,
    ) -> int:
        row = connection.execute(
            """
            INSERT INTO ops.data_source(code, name, base_url, license_class)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (code) DO UPDATE
            SET name = EXCLUDED.name,
                base_url = EXCLUDED.base_url,
                license_class = EXCLUDED.license_class
            RETURNING source_id
            """,
            (code, name, base_url, license_class),
        ).fetchone()
        assert row is not None
        return int(row["source_id"])

    @staticmethod
    def _upsert_snapshot(
        *,
        connection: Connection[dict[str, object]],
        run_id: uuid.UUID,
        source_id: int,
        dataset_code: str,
        target_date: date,
        as_of_at: datetime,
        fetched_at: datetime,
        source_available_at: datetime,
        availability_basis: str,
        raw: RawObject,
        is_reconstruction: bool,
    ) -> uuid.UUID:
        snapshot_id = _stable_uuid(
            "source-snapshot",
            f"{source_id}:{dataset_code}:{target_date}:{raw.content_hash}",
        )
        inserted = connection.execute(
            """
            INSERT INTO ops.source_snapshot(
                source_snapshot_id, ingestion_run_id, source_id, dataset_code,
                snapshot_kind, coverage_start, coverage_end, as_of_at, fetched_at,
                source_available_at, storage_uri, content_hash, byte_size,
                license_class, is_reconstruction, availability_basis
            )
            VALUES (%s, %s, %s, %s, 'FULL', %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (
                source_id, dataset_code, coverage_start, coverage_end, content_hash
            ) DO NOTHING
            RETURNING source_snapshot_id
            """,
            (
                snapshot_id,
                run_id,
                source_id,
                dataset_code,
                target_date,
                target_date,
                as_of_at,
                fetched_at,
                source_available_at,
                raw.uri,
                raw.content_hash,
                raw.byte_size,
                "PUBLIC_REFERENCE" if dataset_code == "sp500_universe" else "PROVIDER_TERMS",
                is_reconstruction,
                availability_basis,
            ),
        ).fetchone()
        if inserted is not None:
            return inserted["source_snapshot_id"]
        existing = connection.execute(
            """
            SELECT source_snapshot_id
            FROM ops.source_snapshot
            WHERE source_id = %s
              AND dataset_code = %s
              AND coverage_start = %s
              AND coverage_end = %s
              AND content_hash = %s
            """,
            (source_id, dataset_code, target_date, target_date, raw.content_hash),
        ).fetchone()
        if existing is None:
            raise RuntimeError("Source snapshot conflict could not be resolved")
        return existing["source_snapshot_id"]

    @staticmethod
    def _persist_universe(
        connection: Connection[dict[str, object]],
        run_spec: RunSpec,
        universe: UniverseCollection,
        snapshot_id: uuid.UUID,
    ) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
        universe_id = _stable_uuid("universe", "SP500_WIKIPEDIA")
        version_id = _stable_uuid("universe-version", str(universe.revision_id))
        connection.execute(
            """
            INSERT INTO ref.universe(universe_id, code, name)
            VALUES (%s, 'SP500_WIKIPEDIA', 'S&P 500 Wikipedia revision')
            ON CONFLICT (universe_id) DO NOTHING
            """,
            (universe_id,),
        )
        connection.execute(
            """
            INSERT INTO ref.universe_version(
                universe_version_id, universe_id, provider_revision_id,
                as_of_date, announced_at, effective_at, source_snapshot_id
            )
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (universe_version_id) DO NOTHING
            """,
            (
                version_id,
                universe_id,
                str(universe.revision_id),
                run_spec.target_date,
                universe.revision_at,
                run_spec.cutoff_at,
                snapshot_id,
            ),
        )
        instrument_ids: dict[str, uuid.UUID] = {}
        for member in universe.members:
            issuer_id = _stable_uuid(
                "issuer",
                f"cik:{member.cik}" if member.cik else f"name:{member.security_name}",
            )
            instrument_id = _stable_uuid("instrument", f"{issuer_id}:{member.symbol}")
            instrument_ids[member.symbol] = instrument_id
            connection.execute(
                """
                INSERT INTO ref.issuer(issuer_id, cik, legal_name)
                VALUES (%s, %s, %s)
                ON CONFLICT (issuer_id) DO NOTHING
                """,
                (issuer_id, member.cik, member.security_name),
            )
            connection.execute(
                """
                INSERT INTO ref.instrument(instrument_id, issuer_id)
                VALUES (%s, %s)
                ON CONFLICT (instrument_id) DO NOTHING
                """,
                (instrument_id, issuer_id),
            )
            identifier_id = _stable_uuid(
                "identifier",
                f"{instrument_id}:TICKER:{member.symbol}:{run_spec.target_date}",
            )
            connection.execute(
                """
                INSERT INTO ref.instrument_identifier(
                    identifier_id, instrument_id, id_type, id_value, valid_from,
                    source_available_at, observed_at, source_snapshot_id
                )
                VALUES (%s, %s, 'TICKER', %s, %s, %s, %s, %s)
                ON CONFLICT (identifier_id) DO NOTHING
                """,
                (
                    identifier_id,
                    instrument_id,
                    member.symbol,
                    run_spec.target_date,
                    universe.revision_at,
                    universe.observed_at,
                    snapshot_id,
                ),
            )
            connection.execute(
                """
                INSERT INTO ref.universe_member(
                    universe_version_id, instrument_id, symbol, security_name,
                    sector, sub_industry, provider_symbol
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (universe_version_id, instrument_id) DO NOTHING
                """,
                (
                    version_id,
                    instrument_id,
                    member.symbol,
                    member.security_name,
                    member.sector,
                    member.sub_industry,
                    member.provider_symbol,
                ),
            )
        return version_id, instrument_ids

    @staticmethod
    def _persist_bars(
        connection: Connection[dict[str, object]],
        bars: tuple[DailyBar, ...],
        instrument_ids: dict[str, uuid.UUID],
        source_id: int,
        snapshot_id: uuid.UUID,
        source_available_at: datetime,
        observed_at: datetime,
    ) -> int:
        inserted = 0
        for bar in bars:
            instrument_id = instrument_ids[bar.symbol]
            current = connection.execute(
                """
                SELECT revision_no, open, high, low, close, adjusted_close, volume
                FROM market.daily_bar
                WHERE instrument_id = %s AND session_date = %s AND source_id = %s
                ORDER BY revision_no DESC
                LIMIT 1
                """,
                (instrument_id, bar.session_date, source_id),
            ).fetchone()
            values = (
                _price(bar.open),
                _price(bar.high),
                _price(bar.low),
                _price(bar.close),
                _price(bar.adjusted_close),
                bar.volume,
            )
            if current is not None:
                current_values = (
                    current["open"],
                    current["high"],
                    current["low"],
                    current["close"],
                    current["adjusted_close"],
                    current["volume"],
                )
                if current_values == values:
                    revision_no = int(current["revision_no"])
                else:
                    revision_no = int(current["revision_no"]) + 1
            else:
                revision_no = 1
            if current is None or int(current["revision_no"]) != revision_no:
                connection.execute(
                    """
                    INSERT INTO market.daily_bar(
                        instrument_id, session_date, source_id, revision_no,
                        open, high, low, close, adjusted_close, volume,
                        source_timestamp, source_available_at, observed_at, source_snapshot_id
                    )
                    VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s,
                        %s, %s, %s, %s, %s, %s
                    )
                    """,
                    (
                        instrument_id,
                        bar.session_date,
                        source_id,
                        revision_no,
                        *values,
                        bar.source_timestamp,
                        source_available_at,
                        observed_at,
                        snapshot_id,
                    ),
                )
                inserted += 1
            connection.execute(
                """
                INSERT INTO market.daily_bar_observation(
                    source_snapshot_id, instrument_id, session_date,
                    source_id, revision_no, observed_at
                )
                VALUES (%s, %s, %s, %s, %s, %s)
                ON CONFLICT DO NOTHING
                """,
                (
                    snapshot_id,
                    instrument_id,
                    bar.session_date,
                    source_id,
                    revision_no,
                    observed_at,
                ),
            )
        return inserted

    def verify_loaded_date(self, target_date: date) -> dict[str, object]:
        with self.connect() as connection:
            row = connection.execute(
                """
                WITH latest_context AS (
                    SELECT ec.input_manifest_id
                    FROM ops.execution_context ec
                    JOIN ops.input_manifest_member imm
                      ON imm.input_manifest_id = ec.input_manifest_id
                    JOIN ops.source_snapshot ss
                      ON ss.source_snapshot_id = imm.source_snapshot_id
                    JOIN ops.ingestion_run ir
                      ON ir.ingestion_run_id = ss.ingestion_run_id
                    WHERE ir.target_date = %s
                    ORDER BY ec.created_at DESC
                    LIMIT 1
                ),
                context_bars AS (
                    SELECT DISTINCT
                        obs.instrument_id,
                        obs.session_date,
                        obs.source_id,
                        obs.revision_no
                    FROM latest_context lc
                    JOIN ops.input_manifest_member imm
                      ON imm.input_manifest_id = lc.input_manifest_id
                     AND imm.dataset_code = 'daily_bar'
                    JOIN market.daily_bar_observation obs
                      ON obs.source_snapshot_id = imm.source_snapshot_id
                )
                SELECT
                    (
                        SELECT count(*) FROM context_bars WHERE session_date = %s
                    ) AS target_rows,
                    (
                        SELECT count(*) FROM context_bars WHERE session_date > %s
                    ) AS future_rows,
                    (
                        SELECT max(session_date) FROM context_bars
                    ) AS max_session_date,
                    (
                        SELECT count(*)
                        FROM market.daily_bar
                        WHERE session_date = %s
                    ) AS logical_target_rows,
                    (
                        SELECT count(*)
                        FROM ref.universe_member um
                        JOIN ref.universe_version uv USING (universe_version_id)
                        JOIN ops.source_snapshot ss USING (source_snapshot_id)
                        JOIN ops.ingestion_run ir USING (ingestion_run_id)
                        WHERE ir.target_date = %s
                    ) AS universe_members
                """,
                (
                    target_date,
                    target_date,
                    target_date,
                    target_date,
                    target_date,
                ),
            ).fetchone()
            assert row is not None
            return dict(row)

    def verify_database_fence(self, run_spec: RunSpec) -> bool:
        harness_source = "TEMPORAL_FENCE_HARNESS"
        with self.connect() as connection, connection.transaction():
            source_id = self._upsert_source(
                connection,
                harness_source,
                "Temporal fence harness",
                "https://example.invalid",
                "TEST",
            )
        try:
            with self.connect() as connection, connection.transaction():
                run_id = uuid.uuid4()
                connection.execute(
                    """
                    INSERT INTO ops.ingestion_run(
                        ingestion_run_id, dataset_code, target_date, cutoff_at,
                        knowledge_mode, config_hash, status
                    )
                    VALUES (%s, 'temporal_fence_harness', %s, %s, %s, %s, 'RUNNING')
                    """,
                    (
                        run_id,
                        run_spec.target_date,
                        run_spec.cutoff_at,
                        run_spec.knowledge_mode.value,
                        uuid.uuid4().hex,
                    ),
                )
                connection.execute(
                    """
                    INSERT INTO ops.source_snapshot(
                        source_snapshot_id, ingestion_run_id, source_id, dataset_code,
                        snapshot_kind, coverage_start, coverage_end, as_of_at, fetched_at,
                        source_available_at, storage_uri, content_hash, byte_size,
                        license_class, is_reconstruction
                    )
                    VALUES (%s, %s, %s, 'harness', 'FULL', %s, %s, %s, now(),
                            %s, 'file:///invalid', %s, 0, 'TEST', true)
                    """,
                    (
                        uuid.uuid4(),
                        run_id,
                        source_id,
                        run_spec.target_date,
                        run_spec.target_date + timedelta(days=1),
                        run_spec.cutoff_at,
                        run_spec.cutoff_at,
                        uuid.uuid4().hex,
                    ),
                )
        except psycopg.errors.RaiseException as error:
            if "temporal fence" not in str(error):
                raise
            return True
        raise AssertionError("Database temporal fence accepted future snapshot coverage")
