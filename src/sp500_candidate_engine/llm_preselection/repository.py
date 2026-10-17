from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime

from psycopg.types.json import Jsonb

from sp500_candidate_engine.database import _canonical_hash, _stable_uuid
from sp500_candidate_engine.llm_preselection.evidence import EvidenceLink, EvidencePacket
from sp500_candidate_engine.llm_preselection.ranker import (
    CallAttempt,
    RankingResult,
)
from sp500_candidate_engine.llm_preselection.temporal import validate_packet, validate_revision_time


class LlmPreselectionRepository:
    def __init__(self, connection: object) -> None:
        self.connection = connection

    def read_cached_inputs(
        self, *, execution_context_id: uuid.UUID, target_session: date,
        policy_hash: str, schema_version: str, cutoff_at: datetime, knowledge_mode: str,
    ) -> tuple[uuid.UUID, tuple[EvidencePacket, ...], tuple[dict[str, object], ...]] | None:
        if knowledge_mode not in {"OPERATIONAL_REPLAY", "HISTORICAL_RECONSTRUCTION"}:
            raise ValueError("Unknown cached input replay mode")
        run = self.connection.execute(  # type: ignore[attr-defined]
            """
            SELECT ranking.llm_ranking_run_id, ranking.eligible_count
            FROM analytics.llm_ranking_run ranking
            WHERE execution_context_id=%s AND price_session_date=%s
              AND policy_hash=%s AND evidence_schema_version=%s
              AND window_config->>'input_identity_version' IN ('2','3','4','5')
              AND eligible_count >= 20
              AND (SELECT count(*) FROM analytics.llm_evidence_packet packet
                   WHERE packet.llm_ranking_run_id=ranking.llm_ranking_run_id)
                  =ranking.eligible_count
            ORDER BY ranking.finished_at DESC,ranking.llm_ranking_run_id DESC LIMIT 1
            """,
            (execution_context_id, target_session, policy_hash, schema_version),
        ).fetchone()
        if run is None:
            return None
        run_id = run["llm_ranking_run_id"]
        rows = self.connection.execute(  # type: ignore[attr-defined]
            "SELECT * FROM analytics.llm_evidence_packet WHERE llm_ranking_run_id=%s "
            "ORDER BY instrument_id", (run_id,),
        ).fetchall()
        if len(rows) != run["eligible_count"]:
            raise ValueError("Cached LLM packet count mismatch")
        links = self.connection.execute(  # type: ignore[attr-defined]
            """
            SELECT link.*, revision.revision_no, revision.observed_at AS revision_observed_at
            FROM analytics.llm_evidence_link link
            LEFT JOIN event.event_revision revision ON revision.event_revision_id = CASE
                WHEN link.source_kind IN ('NEWS', 'EARNINGS', 'EVENT')
                THEN link.entity_key::uuid END
            WHERE link.llm_ranking_run_id=%s
            ORDER BY link.instrument_id,link.source_kind,link.entity_key,link.source_snapshot_id
            """, (run_id,),
        ).fetchall()
        snapshots = self.connection.execute(  # type: ignore[attr-defined]
            """
            SELECT snapshot.source_snapshot_id,snapshot.source_available_at,snapshot.fetched_at
            FROM ops.execution_context context
            JOIN ops.input_manifest_member member USING(input_manifest_id)
            JOIN ops.source_snapshot snapshot USING(source_snapshot_id)
            WHERE context.execution_context_id=%s
            """, (execution_context_id,),
        ).fetchall()
        by_snapshot = {row["source_snapshot_id"]: row for row in snapshots}
        audit = self.connection.execute(  # type: ignore[attr-defined]
            "SELECT decision FROM analytics.llm_screening_decision WHERE llm_ranking_run_id=%s "
            "ORDER BY issuer_id", (run_id,),
        ).fetchall()
        packets = []
        for row in rows:
            packet = row["packet"]
            if (
                not isinstance(packet, dict) or _canonical_hash(packet) != row["packet_hash"]
                or packet.get("execution_context_id") != str(execution_context_id)
                or packet.get("target_session") != target_session.isoformat()
                or packet.get("cutoff_at") != cutoff_at.isoformat()
                or packet.get("schema_version") != schema_version
            ):
                raise ValueError("Cached LLM packet identity/hash mismatch")
            packet_links = []
            for link in links:
                if link["instrument_id"] != row["instrument_id"]:
                    continue
                validate_revision_time(
                    source_kind=link["source_kind"], revision_no=link["revision_no"],
                    revision_observed_at=link["revision_observed_at"], cutoff_at=cutoff_at,
                )
                snapshot = by_snapshot.get(link["source_snapshot_id"])
                if (
                    snapshot is None
                    or link["source_available_at"] > cutoff_at
                    or (knowledge_mode == "OPERATIONAL_REPLAY" and (
                        snapshot["source_available_at"] > cutoff_at
                        or snapshot["fetched_at"] > cutoff_at
                        or (link["observed_at"] is not None and link["observed_at"] > cutoff_at)
                        or (link["observed_at"] is None and link["source_kind"] != "UNIVERSE")
                    ))
                ):
                    raise ValueError("Cached LLM packet exceeds its frozen manifest/cutoff")
                canonical_id = _stable_uuid("llm-evidence-link", (
                    f"{row['instrument_id']}:{link['source_kind']}:{link['entity_key']}:"
                    f"{link['source_snapshot_id']}"
                ))
                packet_links.append(EvidenceLink(
                    canonical_id, link["source_snapshot_id"], link["source_kind"],
                    link["entity_key"],
                    link["source_available_at"], link["observed_at"], link["event_at"],
                ))
            identity = packet["identity"]
            if not isinstance(identity, dict) or (
                identity["instrument_id"] != str(row["instrument_id"])
            ):
                raise ValueError("Cached packet instrument identity mismatch")
            if not packet_links:
                raise ValueError("Cached LLM packet has no source lineage")
            packets.append(EvidencePacket(
                row["instrument_id"], uuid.UUID(str(identity["issuer_id"])), identity["symbol"],
                identity["company_name"], identity.get("sector"), packet, row["packet_hash"],
                row["estimated_tokens"], row["section_counts"], tuple(row["missing_sections"]),
                tuple(row["truncated_sections"]), tuple(packet_links),
            ))
            validate_packet(
                packets[-1], cutoff_at=cutoff_at, target_session=target_session,
                execution_context_id=execution_context_id, knowledge_mode=knowledge_mode,
            )
        decisions = tuple(row["decision"] for row in audit)
        selected = {str(row["instrument_id"]) for row in decisions if row["selected"]}
        if selected != {str(packet.instrument_id) for packet in packets}:
            raise ValueError("Cached LLM screening set does not match the packet set")
        return uuid.UUID(str(run_id)), tuple(packets), decisions

    def find_cached_call(
        self, *, input_hash: str, policy_hash: str, deployment: str, api_version: str,
        execution_context_id: uuid.UUID,
        include_failed: bool = False,
    ) -> dict[str, object] | None:
        return self.connection.execute(  # type: ignore[attr-defined]
            """
            SELECT attempt.llm_call_attempt_id, attempt.response_output, attempt.output_hash
            FROM analytics.llm_call_attempt attempt
            JOIN analytics.llm_ranking_run ranking USING (llm_ranking_run_id)
            WHERE attempt.input_hash = %s AND ranking.policy_hash = %s
              AND attempt.deployment = %s AND attempt.api_version = %s
              AND ranking.execution_context_id = %s
              AND (
                  attempt.status = 'SUCCEEDED'
                  OR (%s::boolean AND attempt.status = 'FAILED'
                      AND attempt.error_code = 'OUTPUT_VALIDATION_FAILED')
              )
              AND attempt.response_output IS NOT NULL
              AND attempt.cache_source_attempt_id IS NULL
            ORDER BY (attempt.status = 'SUCCEEDED') DESC,
                attempt.finished_at, attempt.llm_call_attempt_id LIMIT 1
            """,
            (input_hash, policy_hash, deployment, api_version,
             execution_context_id, include_failed),
        ).fetchone()

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
        screening_audit: tuple[dict[str, object], ...] = (),
        policy_hash: str | None = None,
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
                failure_code, started_at, finished_at, policy_hash
            )
            VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                %s, %s, %s, %s, %s, %s, %s, %s
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
                policy_hash,
            ),
        )
        for decision in screening_audit:
            self.connection.execute(  # type: ignore[attr-defined]
                """
                INSERT INTO analytics.llm_screening_decision(
                    llm_ranking_run_id, issuer_id, instrument_id, decision
                ) VALUES (%s, %s, %s, %s)
                """,
                (llm_ranking_run_id, uuid.UUID(str(decision["issuer_id"])),
                 uuid.UUID(str(decision["instrument_id"])), Jsonb(decision)),
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
                        uncertainty, reason_codes, rationale, output_hash,
                        criterion_evidence, missing_reasons, weight_denominator, supported_count
                    )
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
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
                        Jsonb(list(assessment.criterion_evidence)),
                        Jsonb(assessment.missing_reasons),
                        assessment.weight_denominator,
                        assessment.supported_count,
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
                    total_tokens, started_at, finished_at, response_output, cache_source_attempt_id
                )
                VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
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
                    Jsonb(attempt.response_output) if attempt.response_output is not None else None,
                    attempt.cache_source_attempt_id,
                ),
            )
