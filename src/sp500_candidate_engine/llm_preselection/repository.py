from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime

from psycopg.types.json import Jsonb

from sp500_candidate_engine.llm_preselection.evidence import EvidencePacket
from sp500_candidate_engine.llm_preselection.ranker import (
    CallAttempt,
    RankingResult,
)


class LlmPreselectionRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def find_successful_run(
        self,
        *,
        execution_context_id: uuid.UUID,
        policy_version: str,
        prompt_version: str,
        deployment: str,
        evidence_schema_version: str,
        input_hash: str,
    ) -> dict[str, object] | None:
        return self.connection.execute(  # type: ignore[attr-defined]
            """
            SELECT ranking.llm_ranking_run_id, selection.run_id,
                ranking.selected_count
            FROM analytics.llm_ranking_run ranking
            JOIN selection.llm_preselection_run selection
              ON selection.llm_ranking_run_id = ranking.llm_ranking_run_id
            WHERE ranking.execution_context_id = %s
              AND ranking.policy_version = %s
              AND ranking.prompt_version = %s
              AND ranking.deployment = %s
              AND ranking.evidence_schema_version = %s
              AND ranking.input_hash = %s
              AND ranking.status = 'SUCCEEDED'
            """,
            (
                execution_context_id,
                policy_version,
                prompt_version,
                deployment,
                evidence_schema_version,
                input_hash,
            ),
        ).fetchone()

    def persist(
        self,
        *,
        llm_ranking_run_id: uuid.UUID,
        selection_run_id: uuid.UUID,
        execution_context_id: uuid.UUID,
        price_session_date: date,
        cutoff_at: datetime,
        generated_at: datetime,
        policy_version: str,
        prompt_version: str,
        deployment: str,
        api_version: str,
        evidence_schema_version: str,
        window_config: dict[str, object],
        input_hash: str,
        packets: tuple[EvidencePacket, ...],
        status: str,
        failure_code: str | None,
        attempts: tuple[CallAttempt, ...],
        result: RankingResult | None,
        started_at: datetime,
        finished_at: datetime,
    ) -> None:
        selected_count = len(result.candidates) if result is not None else 0
        assessed_count = len(result.assessments) if result is not None else 0
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO analytics.llm_ranking_run(
                llm_ranking_run_id, execution_context_id, price_session_date,
                cutoff_at, policy_version, prompt_version, deployment,
                api_version, evidence_schema_version, window_config, input_hash,
                status, eligible_count, assessed_count, selected_count,
                failure_code, started_at, finished_at
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s
            )
            """,
            (
                llm_ranking_run_id,
                execution_context_id,
                price_session_date,
                cutoff_at,
                policy_version,
                prompt_version,
                deployment,
                api_version,
                evidence_schema_version,
                Jsonb(window_config),
                input_hash,
                status,
                len(packets),
                assessed_count,
                selected_count,
                failure_code,
                started_at,
                finished_at,
            ),
        )
        for packet in packets:
            self.connection.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO analytics.llm_evidence_packet(
                    llm_ranking_run_id, instrument_id, packet_schema_version,
                    packet, packet_hash, estimated_tokens, section_counts,
                    missing_sections, truncated_sections
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    llm_ranking_run_id,
                    packet.instrument_id,
                    evidence_schema_version,
                    Jsonb(packet.packet),
                    packet.packet_hash,
                    packet.estimated_tokens,
                    Jsonb(packet.section_counts),
                    list(packet.missing_sections),
                    list(packet.truncated_sections),
                ),
            )
            for link in packet.links:
                self.connection.execute(  # type: ignore[attr-defined]
                    """
                    INSERT INTO analytics.llm_evidence_link(
                        evidence_link_id, llm_ranking_run_id, instrument_id,
                        source_snapshot_id, source_kind, entity_key,
                        source_available_at, observed_at, event_at
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        link.evidence_link_id,
                        llm_ranking_run_id,
                        packet.instrument_id,
                        link.source_snapshot_id,
                        link.source_kind,
                        link.entity_key,
                        link.source_available_at,
                        link.observed_at,
                        link.event_at,
                    ),
                )
        self._persist_attempts(
            llm_ranking_run_id=llm_ranking_run_id,
            attempts=attempts,
            prompt_version=prompt_version,
            deployment=deployment,
            api_version=api_version,
        )
        if result is not None:
            assessment_by_id = {
                assessment.instrument_id: assessment
                for assessment in result.assessments
            }
            for assessment in result.assessments:
                self.connection.execute(  # type: ignore[attr-defined]
                    """
                    INSERT INTO analytics.llm_instrument_assessment(
                        llm_ranking_run_id, instrument_id, batch_no,
                        first_stage_rank, score, sub_scores, evidence_quality,
                        uncertainty, reason_codes, rationale, output_hash
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    """,
                    (
                        llm_ranking_run_id,
                        assessment.instrument_id,
                        assessment.batch_no,
                        assessment.first_stage_rank,
                        assessment.score,
                        Jsonb(assessment.sub_scores),
                        assessment.evidence_quality,
                        assessment.uncertainty,
                        list(assessment.reason_codes),
                        assessment.rationale,
                        assessment.output_hash,
                    ),
                )
        else:
            assessment_by_id = {}
        self.connection.execute(  # type: ignore[attr-defined]
            """
            INSERT INTO selection.llm_preselection_run(
                run_id, llm_ranking_run_id, price_session_date, cutoff_at,
                generated_at, policy_version, requested_count, selected_count,
                status, failure_code
            )
            VALUES (%s, %s, %s, %s, %s, %s, 20, %s, %s, %s)
            """,
            (
                selection_run_id,
                llm_ranking_run_id,
                price_session_date,
                cutoff_at,
                generated_at,
                policy_version,
                selected_count,
                status,
                failure_code,
            ),
        )
        if result is None:
            return
        packet_by_id = {packet.instrument_id: packet for packet in packets}
        for candidate in result.candidates:
            assessment = assessment_by_id[candidate.instrument_id]
            packet = packet_by_id[candidate.instrument_id]
            self.connection.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO selection.llm_preselection_candidate(
                    run_id, instrument_id, position, score, first_stage_rank,
                    final_rank, evidence_quality, reason_codes, symbol,
                    company_name, sector
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    selection_run_id,
                    candidate.instrument_id,
                    candidate.position,
                    candidate.score,
                    assessment.first_stage_rank,
                    candidate.position,
                    assessment.evidence_quality,
                    list(candidate.reason_codes),
                    packet.symbol,
                    packet.company_name,
                    packet.sector,
                ),
            )
            for priority, evidence_link_id in enumerate(
                candidate.evidence_ids, start=1
            ):
                self.connection.execute(  # type: ignore[attr-defined]
                    """
                    INSERT INTO selection.llm_preselection_evidence(
                        run_id, instrument_id, evidence_link_id, priority
                    )
                    VALUES (%s, %s, %s, %s)
                    """,
                    (
                        selection_run_id,
                        candidate.instrument_id,
                        evidence_link_id,
                        priority,
                    ),
                )

    def _persist_attempts(
        self,
        *,
        llm_ranking_run_id: uuid.UUID,
        attempts: Iterable[CallAttempt],
        prompt_version: str,
        deployment: str,
        api_version: str,
    ) -> None:
        for attempt in attempts:
            self.connection.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO analytics.llm_call_attempt(
                    llm_call_attempt_id, llm_ranking_run_id, call_stage,
                    batch_no, attempt_no, input_hash, output_hash,
                    prompt_version, deployment, api_version, status,
                    http_status, error_code, input_tokens, output_tokens,
                    total_tokens, started_at, finished_at
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s
                )
                """,
                (
                    attempt.call_attempt_id,
                    llm_ranking_run_id,
                    attempt.stage,
                    attempt.batch_no,
                    attempt.attempt_no,
                    attempt.input_hash,
                    attempt.output_hash,
                    prompt_version,
                    deployment,
                    api_version,
                    attempt.status,
                    attempt.http_status,
                    attempt.error_code,
                    attempt.input_tokens,
                    attempt.output_tokens,
                    attempt.total_tokens,
                    attempt.started_at,
                    attempt.finished_at,
                ),
            )
