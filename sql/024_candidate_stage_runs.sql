CREATE TABLE IF NOT EXISTS ops.candidate_stage_run (
    stage_run_id uuid PRIMARY KEY,
    stage text NOT NULL CHECK (stage IN ('QUANTITATIVE', 'LLM_PRESELECTION', 'FUSION')),
    target_session date NOT NULL,
    execution_context_id uuid NOT NULL REFERENCES ops.execution_context(execution_context_id),
    model_purpose text CHECK (model_purpose IN ('SHORT_5D', 'MEDIUM_20D')),
    request_payload jsonb NOT NULL,
    request_hash text NOT NULL,
    contract jsonb NOT NULL,
    contract_hash text NOT NULL,
    input_hash text NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    retry_of_run_id uuid REFERENCES ops.candidate_stage_run(stage_run_id),
    owner text NOT NULL CHECK (owner IN ('API', 'CLI')),
    status text NOT NULL CHECK (
        status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'SHORTFALL', 'FAILED')
    ),
    result jsonb,
    failure_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    started_at timestamptz,
    finished_at timestamptz,
    CHECK (
        (status IN ('PENDING', 'RUNNING') AND finished_at IS NULL AND failure_code IS NULL)
        OR (status = 'SUCCEEDED' AND result IS NOT NULL
            AND finished_at IS NOT NULL AND failure_code IS NULL)
        OR (status IN ('SHORTFALL', 'FAILED')
            AND finished_at IS NOT NULL AND failure_code IS NOT NULL)
    ),
    CHECK (finished_at IS NULL OR started_at IS NULL OR finished_at >= started_at),
    CHECK (
        (stage = 'LLM_PRESELECTION' AND model_purpose IS NULL)
        OR (stage = 'QUANTITATIVE' AND model_purpose IS NOT NULL)
        OR (stage = 'FUSION' AND model_purpose IS NOT NULL AND model_purpose = 'MEDIUM_20D')
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS candidate_stage_one_active_input
    ON ops.candidate_stage_run(input_hash)
    WHERE status IN ('PENDING', 'RUNNING');
CREATE INDEX IF NOT EXISTS candidate_stage_date
    ON ops.candidate_stage_run(target_session DESC, created_at DESC, stage_run_id DESC);

CREATE OR REPLACE FUNCTION ops.protect_candidate_stage_run()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    IF TG_OP = 'DELETE' THEN
        RAISE EXCEPTION 'candidate stage history cannot be deleted';
    END IF;
    IF OLD.status IN ('SUCCEEDED', 'SHORTFALL', 'FAILED') THEN
        RAISE EXCEPTION 'terminal candidate stage is immutable';
    END IF;
    IF (NEW.stage_run_id, NEW.stage, NEW.target_session, NEW.execution_context_id,
        NEW.model_purpose, NEW.request_payload, NEW.request_hash, NEW.contract,
        NEW.contract_hash, NEW.input_hash, NEW.idempotency_key, NEW.retry_of_run_id,
        NEW.owner, NEW.created_at)
       IS DISTINCT FROM
       (OLD.stage_run_id, OLD.stage, OLD.target_session, OLD.execution_context_id,
        OLD.model_purpose, OLD.request_payload, OLD.request_hash, OLD.contract,
        OLD.contract_hash, OLD.input_hash, OLD.idempotency_key, OLD.retry_of_run_id,
        OLD.owner, OLD.created_at) THEN
        RAISE EXCEPTION 'candidate stage identity is immutable';
    END IF;
    IF NOT (
        (OLD.status = 'PENDING' AND NEW.status IN ('RUNNING', 'FAILED'))
        OR (OLD.status = 'RUNNING' AND NEW.status IN ('SUCCEEDED', 'SHORTFALL', 'FAILED'))
    ) THEN
        RAISE EXCEPTION 'invalid candidate stage transition';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS protect_candidate_stage_run ON ops.candidate_stage_run;
CREATE TRIGGER protect_candidate_stage_run BEFORE UPDATE OR DELETE
ON ops.candidate_stage_run FOR EACH ROW EXECUTE FUNCTION ops.protect_candidate_stage_run();

INSERT INTO ops.schema_migration(version) VALUES ('024_candidate_stage_runs')
ON CONFLICT (version) DO NOTHING;
