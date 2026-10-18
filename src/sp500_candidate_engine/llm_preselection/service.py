from __future__ import annotations

import asyncio
import os
import uuid
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime
from pathlib import Path

from sp500_candidate_engine.analytics.source_repository import SourceRepository
from sp500_candidate_engine.config import Settings
from sp500_candidate_engine.database import Database, _canonical_hash, _stable_uuid
from sp500_candidate_engine.llm_preselection.config import (
    LlmPreselectionConfig,
    load_llm_preselection_config,
)
from sp500_candidate_engine.llm_preselection.enrichment_contract import ENRICHMENT_VERSION
from sp500_candidate_engine.llm_preselection.event_ranker import EventPreselectionRanker
from sp500_candidate_engine.llm_preselection.evidence import EvidencePacket, EvidencePacketBuilder
from sp500_candidate_engine.llm_preselection.external_enrichment import LlmSearchEnricher
from sp500_candidate_engine.llm_preselection.ranker import (
    AzureOpenAIPreselectionRanker,
    CachedCompletion,
    LlmRankerSettings,
    LlmRankingError,
)
from sp500_candidate_engine.llm_preselection.repository import (
    LlmPreselectionRepository,
)
from sp500_candidate_engine.llm_preselection.summaries import SUMMARY_VERSION
from sp500_candidate_engine.llm_preselection.temporal import (
    TEMPORAL_HARNESS_VERSION,
    validate_packet,
)


@dataclass(frozen=True)
class LlmPreselectionSummary:
    llm_ranking_run_id: uuid.UUID
    selection_run_id: uuid.UUID
    price_session_date: date
    status: str
    selected_count: int
    reused: bool
    failure_code: str | None = None


def _reused_summary(row: dict[str, object], target_session: date) -> LlmPreselectionSummary:
    count = row["selected_count"]
    if type(count) is not int or count != 20:
        raise ValueError("Stored successful LLM run must contain exactly 20 candidates")
    return LlmPreselectionSummary(
        uuid.UUID(str(row["llm_ranking_run_id"])),
        uuid.UUID(str(row["run_id"])),
        target_session,
        "SUCCEEDED",
        count,
        True,
    )


class LlmPreselectionService:
    def __init__(
        self,
        database: Database,
        config: LlmPreselectionConfig,
        ranker_settings: LlmRankerSettings,
        *,
        ranker: AzureOpenAIPreselectionRanker | None = None,
        enricher: LlmSearchEnricher | None = None,
        db_read_workers: int = 4,
    ) -> None:
        self.database = database
        self.config = config
        self.ranker_settings = ranker_settings
        self.enricher = enricher
        self.db_read_workers = db_read_workers
        if type(db_read_workers) is not int or not 1 <= db_read_workers <= 16:
            raise ValueError("Evidence DB workers must be between 1 and 16")
        if config.enrichment is not None and enricher is None:
            raise ValueError("Verified scoring requires an external artifact verifier")
        if config.enrichment is None and enricher is not None:
            raise ValueError("External scoring must not change an existing policy implicitly")
        ranker_class = (
            EventPreselectionRanker if config.event_policy else AzureOpenAIPreselectionRanker
        )
        self.ranker = ranker or ranker_class(ranker_settings, config)
        if config.event_policy:
            self.ranker.response_cache = self._read_cached_completion
        if self.enricher is not None:
            self.enricher.rate_limiter = self.ranker.rate_limiter

    def _read_cached_completion(
        self, input_hash: str, execution_context_id: uuid.UUID, include_failed: bool
    ) -> CachedCompletion | None:
        with self.database.connect() as connection:
            cached = LlmPreselectionRepository(connection).find_cached_call(
                input_hash=input_hash,
                policy_hash=self.config.versioned.config_hash,
                deployment=self.ranker_settings.deployment,
                api_version=self.ranker_settings.api_version,
                execution_context_id=execution_context_id,
                include_failed=include_failed,
            )
        if cached is None:
            return None
        output = cached["response_output"]
        if not isinstance(output, dict):
            raise ValueError("Stored LLM response is not an object")
        return CachedCompletion(
            output, str(cached["output_hash"]), uuid.UUID(str(cached["llm_call_attempt_id"]))
        )

    async def run(
        self,
        *,
        target_session: date,
        execution_context_id: uuid.UUID,
    ) -> LlmPreselectionSummary:
        if not self.config.event_policy:
            return await self._run(
                target_session=target_session, execution_context_id=execution_context_id
            )
        key = "llm-evaluate-" + _canonical_hash(
            {
                "context": execution_context_id,
                "session": target_session,
                "policy": self.config.versioned.config_hash,
                "deployment": self.ranker_settings.deployment,
                "api_version": self.ranker_settings.api_version,
            }
        )
        with self.database.connect(autocommit=True) as lock_connection:
            await asyncio.to_thread(
                lock_connection.execute,
                "SELECT pg_advisory_lock(hashtextextended(%s, 0))",
                (key,),
            )
            try:
                return await self._run(
                    target_session=target_session, execution_context_id=execution_context_id
                )
            finally:
                await asyncio.to_thread(
                    lock_connection.execute,
                    "SELECT pg_advisory_unlock(hashtextextended(%s, 0))",
                    (key,),
                )

    async def _run(
        self, *, target_session: date, execution_context_id: uuid.UUID
    ) -> LlmPreselectionSummary:
        started_at = datetime.now(UTC)
        context, builder, packets, cache_source_id = await asyncio.to_thread(
            self._prepare_inputs, target_session=target_session,
            execution_context_id=execution_context_id,
        )
        cutoff_at = context["cutoff_at"]
        if not isinstance(cutoff_at, datetime):
            raise TypeError("execution context cutoff_at must be datetime")
        if self.enricher is not None:
            packets = await self.enricher.enrich(
                packets,
                knowledge_mode=str(context["knowledge_mode"]),
            )
        return await self._rank_inputs(
            target_session=target_session, execution_context_id=execution_context_id,
            started_at=started_at, context=context, builder=builder, packets=packets,
            cache_source_id=cache_source_id,
        )

    def _prepare_inputs(
        self, *, target_session: date, execution_context_id: uuid.UUID,
    ) -> tuple[
        dict[str, object], EvidencePacketBuilder, tuple[EvidencePacket, ...], uuid.UUID | None
    ]:
        with self.database.connect() as connection:
            connection.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY")
            source = SourceRepository(connection)
            context = source.read_context(execution_context_id=execution_context_id)
            builder = EvidencePacketBuilder(source, self.config)
            cached = None
            if self.config.event_policy:
                source.validate_context_manifest(execution_context_id=execution_context_id)
                cutoff = context["cutoff_at"]
                if not isinstance(cutoff, datetime):
                    raise TypeError("Context cutoff must be a datetime")
                cached = LlmPreselectionRepository(connection).read_cached_inputs(
                    execution_context_id=execution_context_id,
                    target_session=target_session,
                    policy_hash=self.config.versioned.config_hash,
                    schema_version=self.config.evidence_schema_version,
                    cutoff_at=cutoff,
                    knowledge_mode=str(context["knowledge_mode"]),
                )
            if cached is not None:
                _, packets, builder.screening_audit = cached
            else:
                packets = builder.build_all(
                    execution_context_id=execution_context_id,
                    target_session=target_session,
                    database=self.database,
                    max_workers=self.db_read_workers,
                )
            if self.config.event_policy:
                packets = tuple(
                    replace(
                        packet,
                        links=tuple(
                            sorted(
                                packet.links,
                                key=lambda link: (
                                    link.source_kind,
                                    link.entity_key,
                                    str(link.source_snapshot_id),
                                ),
                            )
                        ),
                    )
                    for packet in sorted(packets, key=lambda item: item.instrument_id.hex)
                )
        return context, builder, packets, cached[0] if cached is not None else None

    async def _rank_inputs(
        self, *, target_session: date, execution_context_id: uuid.UUID, started_at: datetime,
        context: dict[str, object], builder: EvidencePacketBuilder,
        packets: tuple[EvidencePacket, ...],
        cache_source_id: uuid.UUID | None,
    ) -> LlmPreselectionSummary:
        cutoff_at = context["cutoff_at"]
        if not isinstance(cutoff_at, datetime):
            raise TypeError("execution context cutoff_at must be datetime")
        if (
            sum(packet.estimated_tokens for packet in packets)
            + (self.enricher.search_input_tokens if self.enricher else 0)
            > self.config.limits.total_input_tokens
        ):
            raise ValueError("Enriched LLM input exceeds its total token budget")
        for packet in packets:
            validate_packet(
                packet,
                cutoff_at=cutoff_at,
                target_session=target_session,
                execution_context_id=execution_context_id if self.config.event_policy else None,
                knowledge_mode=str(context["knowledge_mode"]),
            )
        input_payload: dict[str, object] = {
            "input_identity_version": 5
            if self.config.enrichment
            else (3 if self.config.event_policy else 2),
            "temporal_harness_version": TEMPORAL_HARNESS_VERSION,
            "execution_context_id": execution_context_id,
            "policy_hash": self.config.versioned.config_hash,
            "packet_hashes": [
                {
                    "instrument_id": packet.instrument_id,
                    "packet_hash": packet.packet_hash,
                    "lineage_hash": _canonical_hash(
                        [
                            (
                                link.source_kind,
                                link.entity_key,
                                link.source_snapshot_id,
                                link.source_available_at,
                                link.observed_at,
                            )
                            for link in packet.links
                        ]
                    ),
                }
                for packet in packets
            ],
        }
        if self.config.event_policy:
            input_payload["summary_version"] = SUMMARY_VERSION
            input_payload["screening"] = builder.screening_audit
            input_payload["api_version"] = self.ranker_settings.api_version
        if self.config.enrichment:
            input_payload["external_enrichment_version"] = ENRICHMENT_VERSION
        input_hash = _canonical_hash(input_payload)
        with self.database.connect() as connection:
            reusable = LlmPreselectionRepository(connection).find_successful_run(
                execution_context_id=execution_context_id,
                policy_version=self.config.policy_version,
                prompt_version=self.config.prompt_version,
                deployment=self.ranker_settings.deployment,
                evidence_schema_version=self.config.evidence_schema_version,
                input_hash=input_hash,
            )
        if reusable is not None:
            return _reused_summary(reusable, target_session)

        llm_ranking_run_id = uuid.uuid4()
        selection_run_id = uuid.uuid4()
        packets = tuple(
            replace(
                packet,
                links=tuple(
                    replace(
                        link,
                        evidence_link_id=_stable_uuid(
                            "llm-run-evidence-link",
                            (
                                f"{llm_ranking_run_id}:{packet.instrument_id}:"
                                f"{link.source_kind}:{link.entity_key}:"
                                f"{link.source_snapshot_id}"
                            ),
                        ),
                        citation_id=link.evidence_link_id if self.config.event_policy else None,
                    )
                    for link in packet.links
                ),
            )
            for packet in packets
        )
        result = None
        attempts = ()
        status = "SUCCEEDED"
        failure_code = None
        if len(packets) < self.config.requested_count:
            status = "SHORTFALL"
            failure_code = "INSUFFICIENT_ELIGIBLE_INSTRUMENTS"
        else:
            try:
                result = await self.ranker.rank(
                    llm_ranking_run_id=llm_ranking_run_id,
                    packets=packets,
                )
                attempts = result.attempts
                if len(result.candidates) < self.config.requested_count:
                    status = "SHORTFALL"
                    failure_code = "INSUFFICIENT_EVIDENCE_BACKED_ISSUERS"
            except LlmRankingError as error:
                attempts = error.attempts
                status = "FAILED"
                failure_code = "LLM_RANKING_FAILED"
        finished_at = datetime.now(UTC)
        with self.database.connect() as connection, connection.transaction():
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
                (input_hash,),
            )
            reusable = LlmPreselectionRepository(connection).find_successful_run(
                execution_context_id=execution_context_id,
                policy_version=self.config.policy_version,
                prompt_version=self.config.prompt_version,
                deployment=self.ranker_settings.deployment,
                evidence_schema_version=self.config.evidence_schema_version,
                input_hash=input_hash,
            )
            if reusable is not None:
                return _reused_summary(reusable, target_session)
            LlmPreselectionRepository(connection).persist(
                llm_ranking_run_id=llm_ranking_run_id,
                selection_run_id=selection_run_id,
                execution_context_id=execution_context_id,
                price_session_date=target_session,
                cutoff_at=cutoff_at,
                generated_at=finished_at,
                policy_version=self.config.policy_version,
                prompt_version=self.config.prompt_version,
                deployment=self.ranker_settings.deployment,
                api_version=self.ranker_settings.api_version,
                evidence_schema_version=self.config.evidence_schema_version,
                window_config={
                    **asdict(self.config.windows),
                    "temporal_harness_version": TEMPORAL_HARNESS_VERSION,
                    "summary_version": SUMMARY_VERSION if self.config.event_policy else None,
                    "input_identity_version": 5
                    if self.config.enrichment
                    else (3 if self.config.event_policy else 2),
                    "external_enrichment_version": ENRICHMENT_VERSION
                    if self.config.enrichment
                    else None,
                    "packet_cache_source_run_id": (
                        str(cache_source_id) if cache_source_id is not None else None
                    ),
                },
                input_hash=input_hash,
                packets=packets,
                status=status,
                failure_code=failure_code,
                attempts=attempts,
                result=result,
                started_at=started_at,
                finished_at=finished_at,
                screening_audit=builder.screening_audit,
                policy_hash=self.config.versioned.config_hash,
            )
        return LlmPreselectionSummary(
            llm_ranking_run_id=llm_ranking_run_id,
            selection_run_id=selection_run_id,
            price_session_date=target_session,
            status=status,
            selected_count=0 if result is None else len(result.candidates),
            reused=False,
            failure_code=failure_code,
        )


def create_llm_preselection_service(
    settings: Settings,
    *,
    repository_root: Path,
) -> LlmPreselectionService:
    config = load_runtime_llm_config(repository_root)
    from sp500_candidate_engine.fusion.config import fusion_enabled

    if fusion_enabled() and not config.event_policy:
        raise ValueError("Fusion requires an explicitly selected event LLM policy")
    ranker_settings = LlmRankerSettings.from_env()
    if config.enrichment:
        from sp500_candidate_engine.analytics.azure_openai import (
            AzureOpenAIClient,
            BingGroundingConnection,
            BingGroundingSearchClient,
        )
        from sp500_candidate_engine.llm_preselection.external_enrichment import NativeSearchClient

        ranker = EventPreselectionRanker(ranker_settings, config)
        if not isinstance(ranker.client, AzureOpenAIClient):
            raise ValueError("Native search requires the configured Azure OpenAI client")
        search_client: NativeSearchClient = ranker.client
        if config.enrichment.provider == "AZURE_BING_GROUNDING_PERIOD":
            project = os.getenv("BING_GROUNDING_PROJECT_ENDPOINT", "").strip()
            connection_id = os.getenv("BING_GROUNDING_CONNECTION_ID", "").strip()
            if not project or not connection_id:
                raise ValueError(
                    "Period search requires a Foundry project endpoint and Bing connection"
                )
            search_client = BingGroundingSearchClient(
                ranker.client,
                BingGroundingConnection(project, connection_id, config.windows.news_days),
            )
        return LlmPreselectionService(
            Database(settings),
            config,
            ranker_settings,
            ranker=ranker,
            enricher=LlmSearchEnricher(
                config,
                artifact_directory=settings.raw_data_dir / "llm-search-evidence",
                client=search_client,
                max_concurrency=settings.llm_search_concurrency,
            ),
            db_read_workers=settings.llm_db_read_workers,
        )
    return LlmPreselectionService(
        Database(settings), config, ranker_settings, db_read_workers=settings.llm_db_read_workers
    )


def load_runtime_llm_config(repository_root: Path) -> LlmPreselectionConfig:
    policy_path = Path(
        os.getenv("LLM_PRESELECTION_POLICY_PATH", "config/llm_preselection/policy_v1.yaml")
    )
    path = (repository_root / policy_path).resolve()
    if not path.is_relative_to((repository_root / "config" / "llm_preselection").resolve()):
        raise ValueError("LLM policy must reside in config/llm_preselection")
    config = load_llm_preselection_config(path)
    if config.screening is not None:
        for key, expected in {
            "LLM_SCREENING_MAX_ISSUERS": config.screening.maximum_issuers,
            "LLM_SCREENING_CONTROL_ISSUERS": config.screening.control_issuers,
            "LLM_SCREENING_LOOKBACK_DAYS": config.screening.lookback_days,
            "LLM_SCREENING_EARNINGS_WINDOW_DAYS": config.screening.earnings_window_days,
        }.items():
            if key in os.environ and os.environ[key] != str(expected):
                raise ValueError(f"{key} conflicts with the versioned LLM policy")
    return config
