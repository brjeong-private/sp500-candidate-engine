from __future__ import annotations

from uuid import UUID

from psycopg import Connection
from psycopg.types.json import Jsonb


class CandidateStageConflict(ValueError):
    pass


class CandidateStageRepository:
    def __init__(self, connection: Connection[dict[str, object]]) -> None:
        self.connection = connection

    def lock(self, key: str) -> None:
        self.connection.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", ("candidate-stage:" + key,)
        )

    def by_key(self, key: str) -> dict[str, object] | None:
        return self.connection.execute(
            "SELECT * FROM ops.candidate_stage_run WHERE idempotency_key=%s", (key,)
        ).fetchone()

    def get(self, run_id: UUID) -> dict[str, object]:
        row = self.connection.execute(
            "SELECT * FROM ops.candidate_stage_run WHERE stage_run_id=%s", (run_id,)
        ).fetchone()
        if row is None:
            raise LookupError("Candidate stage run not found")
        return row

    def create(
        self, *, run_id: UUID, payload: dict[str, object], request_hash: str,
        contract: dict[str, object], contract_hash: str, input_hash: str,
        key: str, retry_of: UUID | None, owner: str,
    ) -> dict[str, object]:
        self.lock(input_hash)
        active = self.connection.execute(
            "SELECT stage_run_id FROM ops.candidate_stage_run "
            "WHERE input_hash=%s AND status IN ('PENDING','RUNNING')", (input_hash,),
        ).fetchone()
        if active is not None:
            raise CandidateStageConflict("An identical candidate stage input is already active")
        row = self.connection.execute(
            """
            INSERT INTO ops.candidate_stage_run(
                stage_run_id,stage,target_session,execution_context_id,model_purpose,
                request_payload,request_hash,contract,contract_hash,input_hash,idempotency_key,
                retry_of_run_id,owner,status
            ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING') RETURNING *
            """,
            (run_id, payload["stage"], payload["target_session"], payload["execution_context_id"],
             payload.get("model_purpose"), Jsonb(payload), request_hash, Jsonb(contract),
             contract_hash, input_hash, key, retry_of, owner),
        ).fetchone()
        if row is None:
            raise RuntimeError("Stage insert did not return the stored request")
        return row

    def claim(self, run_id: UUID) -> dict[str, object] | None:
        return self.connection.execute(
            "UPDATE ops.candidate_stage_run SET status='RUNNING',started_at=now() "
            "WHERE stage_run_id=%s AND status='PENDING' RETURNING *", (run_id,),
        ).fetchone()

    def finish(
        self, run_id: UUID, status: str, result: dict[str, object] | None, failure_code: str | None,
    ) -> None:
        row = self.connection.execute(
            "UPDATE ops.candidate_stage_run SET status=%s,result=%s,failure_code=%s,"
            "finished_at=now() WHERE stage_run_id=%s AND status='RUNNING' RETURNING stage_run_id",
            (status, Jsonb(result) if result is not None else None, failure_code, run_id),
        ).fetchone()
        if row is None:
            raise CandidateStageConflict("Stage is not running; terminal state was preserved")

    def reconcile(self) -> int:
        rows = self.connection.execute(
            "UPDATE ops.candidate_stage_run SET status='FAILED',failure_code='INTERRUPTED',"
            "finished_at=now() WHERE owner='API' AND status IN ('PENDING','RUNNING') "
            "RETURNING stage_run_id"
        ).fetchall()
        return len(rows)
