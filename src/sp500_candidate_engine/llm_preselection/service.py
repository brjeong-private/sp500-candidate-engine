from __future__ import annotations

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
from sp500_candidate_engine.llm_preselection.evidence import EvidencePacketBuilder
from sp500_candidate_engine.llm_preselection.ranker import (
    AzureOpenAIPreselectionRanker,
    LlmRankerSettings,
    LlmRankingError,
)
from sp500_candidate_engine.llm_preselection.repository import (
    LlmPreselectionRepository,
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


class LlmPreselectionService:
    def __init__(
        self,
        database: Database,
        config: LlmPreselectionConfig,
        ranker_settings: LlmRankerSettings,
        *,
        ranker: AzureOpenAIPreselectionRanker | None = None,
    ) -> None:
        self.database = database
        self.config = config
        self.ranker_settings = ranker_settings
        self.ranker = ranker or AzureOpenAIPreselectionRanker(
            ranker_settings, config
        )

    async def run(
        self,
        *,
        target_session: date,
        execution_context_id: uuid.UUID,
    ) -> LlmPreselectionSummary:
        started_at = datetime.now(UTC)
        with self.database.connect() as connection:
            source = SourceRepository(connection)
            context = source.read_context(
                execution_context_id=execution_context_id
            )
            packets = EvidencePacketBuilder(source, self.config).build_all(
                execution_context_id=execution_context_id,
                target_session=target_session,
            )
        cutoff_at = context["cutoff_at"]
        if not isinstance(cutoff_at, datetime):
            raise TypeError("execution context cutoff_at must be datetime")
        input_hash = _canonical_hash(
            {
                "execution_context_id": execution_context_id,
                "policy_hash": self.config.versioned.config_hash,
                "packet_hashes": [
                    {
                        "instrument_id": packet.instrument_id,
                        "packet_hash": packet.packet_hash,
                    }
                    for packet in packets
                ],
            }
        )
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
            return LlmPreselectionSummary(
                llm_ranking_run_id=uuid.UUID(
                    str(reusable["llm_ranking_run_id"])
                ),
                selection_run_id=uuid.UUID(str(reusable["run_id"])),
                price_session_date=target_session,
                status="SUCCEEDED",
                selected_count=int(reusable["selected_count"]),
                reused=True,
            )

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
            except LlmRankingError as error:
                attempts = error.attempts
                status = "FAILED"
                failure_code = "LLM_RANKING_FAILED"
        finished_at = datetime.now(UTC)
        with self.database.connect() as connection, connection.transaction():
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
                window_config=asdict(self.config.windows),
                input_hash=input_hash,
                packets=packets,
                status=status,
                failure_code=failure_code,
                attempts=attempts,
                result=result,
                started_at=started_at,
                finished_at=finished_at,
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
    config = load_llm_preselection_config(
        repository_root / "config" / "llm_preselection" / "policy_v1.yaml"
    )
    return LlmPreselectionService(
        Database(settings),
        config,
        LlmRankerSettings.from_env(),
    )
