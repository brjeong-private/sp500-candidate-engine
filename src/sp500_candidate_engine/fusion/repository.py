from __future__ import annotations

import uuid
from dataclasses import asdict
from datetime import date, datetime

from psycopg import Connection
from psycopg.types.json import Jsonb

from sp500_candidate_engine.database import _canonical_hash
from sp500_candidate_engine.fusion.policy import FusionPolicy, FusionResult, rrf_score


class FusionConflictError(ValueError):
    """An idempotency key was reused with different immutable input."""


class FusionRepository:
    def __init__(self, connection: Connection[dict[str, object]]) -> None:
        self.connection = connection

    def read_sources(
        self, quant_id: uuid.UUID | None, llm_id: uuid.UUID | None
    ) -> tuple[dict[str, object] | None, dict[str, object] | None]:
        quant = self.connection.execute(
            """
            SELECT run.*, scoring.execution_context_id, scoring.universe_version_id,
                scoring.status AS scoring_status, scoring.config_hash AS scoring_config_hash,
                scoring.model_version_id, model.model_purpose, model.artifact_hash,
                scoring.score_semantics, model.label_semantics, model.return_policy,
                model.processor_version_id, model.training_feature_run_id,
                model.config_hash AS model_config_hash, scoring.export_run_id,
                export.execution_context_id AS export_context_id, export.status AS export_status,
                NOT EXISTS (
                    SELECT 1 FROM selection.candidate candidate
                    LEFT JOIN analytics.daily_score score
                      ON score.scoring_run_id = scoring.scoring_run_id
                     AND score.instrument_id = candidate.instrument_id
                    WHERE candidate.selection_run_id = run.selection_run_id
                      AND (score.instrument_id IS NULL OR score.score <> candidate.score
                           OR score.rank_overall <> candidate.rank_overall
                           OR score.prediction_horizon <> 20
                           OR score.predicted_return IS NULL
                           OR candidate.predicted_return IS NULL
                           OR score.predicted_return <> candidate.predicted_return
                           OR candidate.quality_status <> 'OK' OR score.quality_status <> 'OK')
                ) AS scores_match,
                COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'instrument_id', candidate.instrument_id,
                        'issuer_id', instrument.issuer_id, 'symbol', member.symbol,
                        'sector', member.sector, 'position', candidate.position,
                        'score', candidate.predicted_return,
                        'original_rank', candidate.rank_overall,
                        'quality_status', candidate.quality_status
                    ) ORDER BY candidate.position)
                    FROM selection.candidate candidate
                    JOIN ref.instrument instrument USING (instrument_id)
                    JOIN ref.universe_member member
                      ON member.instrument_id = candidate.instrument_id
                     AND member.universe_version_id = scoring.universe_version_id
                    WHERE candidate.selection_run_id = run.selection_run_id
                ), '[]'::jsonb) AS candidates
            FROM selection.selection_run run
            JOIN analytics.scoring_run scoring USING (scoring_run_id)
            JOIN analytics.model_version model USING (model_version_id)
            JOIN analytics.qlib_export_run export ON export.export_run_id = scoring.export_run_id
            WHERE run.selection_run_id = %s
            """,
            (quant_id,),
        ).fetchone()
        llm = self.connection.execute(
            """
            SELECT run.*, ranking.execution_context_id, ranking.policy_hash,
                ranking.input_hash, ranking.prompt_version, ranking.deployment,
                ranking.api_version, ranking.evidence_schema_version,
                ranking.status AS ranking_status,
                COALESCE((
                    SELECT jsonb_agg(jsonb_build_object(
                        'instrument_id', candidate.instrument_id,
                        'issuer_id', packet.packet->'identity'->>'issuer_id',
                        'symbol', candidate.symbol, 'sector', candidate.sector,
                        'position', candidate.position, 'score', candidate.score,
                        'original_rank', candidate.first_stage_rank,
                        'supported_count', assessment.supported_count,
                        'weight_denominator', assessment.weight_denominator,
                        'evidence_ids', COALESCE((
                            SELECT jsonb_agg(evidence.evidence_link_id ORDER BY evidence.priority)
                            FROM selection.llm_preselection_evidence evidence
                            WHERE evidence.run_id = candidate.run_id
                              AND evidence.instrument_id = candidate.instrument_id
                        ), '[]'::jsonb)
                    ) ORDER BY candidate.position)
                    FROM selection.llm_preselection_candidate candidate
                    JOIN analytics.llm_evidence_packet packet
                      ON packet.llm_ranking_run_id = run.llm_ranking_run_id
                     AND packet.instrument_id = candidate.instrument_id
                    JOIN analytics.llm_instrument_assessment assessment
                      ON assessment.llm_ranking_run_id = run.llm_ranking_run_id
                     AND assessment.instrument_id = candidate.instrument_id
                    WHERE candidate.run_id = run.run_id
                ), '[]'::jsonb) AS candidates,
                COALESCE((
                    SELECT jsonb_agg(DISTINCT link.entity_key)
                    FROM analytics.llm_evidence_link link
                    WHERE link.llm_ranking_run_id = run.llm_ranking_run_id
                      AND link.source_kind = 'UNIVERSE'
                ), '[]'::jsonb) AS universe_versions
            FROM selection.llm_preselection_run run
            JOIN analytics.llm_ranking_run ranking USING (llm_ranking_run_id)
            WHERE run.run_id = %s
            """,
            (llm_id,),
        ).fetchone()
        return quant, llm

    def persist(
        self, *, context_id: uuid.UUID, quant_id: uuid.UUID | None,
        llm_id: uuid.UUID | None, target_session: date, cutoff_at: datetime,
        policy: FusionPolicy, payload_hash: str, idempotency_key: str,
        provenance: dict[str, object], result: FusionResult | None, failure_code: str | None,
    ) -> dict[str, object]:
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))", (idempotency_key,)
        )
        existing = self.connection.execute(
            "SELECT * FROM selection.fusion_run WHERE idempotency_key = %s",
            (idempotency_key,),
        ).fetchone()
        if existing is not None:
            if existing["payload_hash"] != payload_hash:
                raise FusionConflictError("Fusion idempotency payload conflict")
            return {**existing, "reused": True}
        candidates = result.candidates if result is not None else ()
        if result is not None:
            audit = {row["instrument_id"]: row for row in result.audit}
            if (
                len(audit) != len(result.audit) or len(audit) != result.union_count
                or not set(str(item.instrument_id) for item in candidates) <= audit.keys()
                or sum(row.get("selected") is True for row in result.audit) != len(candidates)
                or any(
                    audit[str(item.instrument_id)].get("selected") is not True
                    or audit[str(item.instrument_id)].get("exclusion_reasons")
                    for item in candidates
                )
                or
                len({item.instrument_id for item in candidates}) != len(candidates)
                or len({item.issuer_id for item in candidates}) != len(candidates)
                or [item.position for item in candidates] != list(range(1, len(candidates) + 1))
                or (result.status == "SUCCEEDED") != (len(candidates) == 20)
                or list(candidates) != sorted(
                    candidates, key=lambda item: (-item.rrf, item.instrument_id.hex)
                )
            ):
                raise ValueError("Invalid Fusion result shape")
            for item in candidates:
                if item.rrf != rrf_score(
                    item.quant.position if item.quant else None,
                    item.llm.position if item.llm else None, k=policy.k,
                ):
                    raise ValueError("Fusion result score mismatch")
        run_id = uuid.uuid4()
        status = result.status if result is not None else "FAILED"
        row = self.connection.execute(
            """
            INSERT INTO selection.fusion_run(
                fusion_run_id, execution_context_id, quant_selection_run_id,
                llm_preselection_run_id, price_session_date, cutoff_at, generated_at,
                policy_version, config_hash, rrf_k, selected_count, union_count,
                status, failure_code, sector_cap_relaxed, provenance, idempotency_key, payload_hash
            ) VALUES (
                %s, %s, %s, %s, %s, %s, now(), %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            ) RETURNING *
            """,
            (run_id, context_id, quant_id, llm_id, target_session, cutoff_at,
             policy.version, policy.config_hash, policy.k, len(candidates),
             result.union_count if result else 0, status, failure_code,
             result.sector_cap_relaxed if result else False, Jsonb(provenance),
             idempotency_key, payload_hash),
        ).fetchone()
        if row is None:
            raise RuntimeError("Fusion insert omitted its stored run")
        for item in candidates:
            candidate: dict[str, object] = {
                "instrument_id": str(item.instrument_id), "issuer_id": str(item.issuer_id),
                "ticker": item.symbol, "sector": item.sector, "position": item.position,
                "quant_rank": item.quant.position if item.quant else None,
                "quant_rank_overall": item.quant.original_rank if item.quant else None,
                "quant_predicted_return": item.quant.score if item.quant else None,
                "llm_rank": item.llm.position if item.llm else None,
                "llm_assessment_rank": item.llm.original_rank if item.llm else None,
                "llm_score": item.llm.score if item.llm else None,
                "rrf_score": float(item.rrf),
                "rrf_numerator": item.rrf.numerator, "rrf_denominator": item.rrf.denominator,
                "selected_by_quant": item.quant is not None,
                "selected_by_llm": item.llm is not None,
                "quality_status": "OK", "risk_status": "PASSED",
                "reason_codes": list(item.reason_codes),
                "source_evidence_refs": list(item.llm.evidence_ids) if item.llm else [],
            }
            self.connection.execute(
                """
                INSERT INTO selection.fusion_candidate(
                    fusion_run_id, instrument_id, issuer_id, position,
                    rrf_numerator, rrf_denominator, candidate
                ) VALUES (%s, %s, %s, %s, %s, %s, %s)
                """,
                (run_id, item.instrument_id, item.issuer_id, item.position,
                 item.rrf.numerator, item.rrf.denominator, Jsonb(candidate)),
            )
        for decision in result.audit if result else ():
            self.connection.execute(
                """
                INSERT INTO selection.fusion_audit(fusion_run_id, instrument_id, decision)
                VALUES (%s, %s, %s)
                """,
                (run_id, uuid.UUID(str(decision["instrument_id"])), Jsonb(decision)),
            )
        return {**row, "reused": False}

    def find_quantitative(
        self, *, context_id: uuid.UUID, target_session: date, policy_version: str,
        policy_hash: str,
    ) -> dict[str, object] | None:
        return self.connection.execute(
            """
            SELECT run.selection_run_id, run.scoring_run_id, scoring.model_version_id,
                scoring.execution_context_id, run.price_session_date,
                run.selected_count AS candidate_count, model.promotion_status AS model_status
            FROM selection.selection_run run
            JOIN analytics.scoring_run scoring USING (scoring_run_id)
            JOIN analytics.model_version model USING (model_version_id)
            WHERE scoring.execution_context_id = %s AND run.price_session_date = %s
              AND run.policy_version = %s AND run.policy_hash = %s
              AND model.model_purpose = 'MEDIUM_20D'
              AND run.status = 'SUCCEEDED' AND scoring.status = 'SUCCEEDED'
              AND run.requested_count = 20 AND run.selected_count = 20
              AND (SELECT count(*) FROM selection.candidate candidate
                   WHERE candidate.selection_run_id = run.selection_run_id) = 20
            ORDER BY run.generated_at DESC, run.selection_run_id DESC LIMIT 1
            """,
            (context_id, target_session, policy_version, policy_hash),
        ).fetchone()


def source_payload_hash(
    quant: dict[str, object] | None, llm: dict[str, object] | None,
    provenance: dict[str, object], policy: FusionPolicy,
) -> str:
    return _canonical_hash({
        "quant": quant, "llm": llm, "provenance": provenance, "policy": asdict(policy),
    })
