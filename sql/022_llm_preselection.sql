ALTER TABLE selection.selection_run
    DROP CONSTRAINT IF EXISTS selection_run_requested_count_check,
    DROP CONSTRAINT IF EXISTS selection_run_check;
ALTER TABLE selection.selection_run
    ADD CONSTRAINT selection_run_requested_count_check
        CHECK (requested_count BETWEEN 5 AND 20),
    ADD CONSTRAINT selection_run_success_count_check
        CHECK (
            (status = 'SUCCEEDED' AND selected_count = requested_count)
            OR status <> 'SUCCEEDED'
        );
ALTER TABLE selection.candidate
    DROP CONSTRAINT IF EXISTS candidate_position_check;
ALTER TABLE selection.candidate
    ADD CONSTRAINT candidate_position_check CHECK (position BETWEEN 1 AND 20);

CREATE TABLE IF NOT EXISTS analytics.llm_ranking_run (
    llm_ranking_run_id uuid PRIMARY KEY,
    execution_context_id uuid NOT NULL
        REFERENCES ops.execution_context(execution_context_id),
    price_session_date date NOT NULL,
    cutoff_at timestamptz NOT NULL,
    policy_version text NOT NULL,
    prompt_version text NOT NULL,
    deployment text NOT NULL,
    api_version text NOT NULL,
    evidence_schema_version text NOT NULL,
    window_config jsonb NOT NULL,
    input_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('SUCCEEDED', 'SHORTFALL', 'FAILED')),
    eligible_count integer NOT NULL CHECK (eligible_count >= 0),
    assessed_count integer NOT NULL CHECK (assessed_count >= 0),
    selected_count integer NOT NULL CHECK (selected_count >= 0 AND selected_count <= 20),
    failure_code text,
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (started_at <= finished_at),
    CHECK (
        (status = 'SUCCEEDED' AND selected_count = 20 AND failure_code IS NULL)
        OR (status IN ('SHORTFALL', 'FAILED') AND failure_code IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS llm_ranking_run_success_identity
    ON analytics.llm_ranking_run(
        execution_context_id, policy_version, prompt_version,
        deployment, evidence_schema_version, input_hash
    )
    WHERE status = 'SUCCEEDED';

CREATE TABLE IF NOT EXISTS analytics.llm_evidence_packet (
    llm_ranking_run_id uuid NOT NULL
        REFERENCES analytics.llm_ranking_run(llm_ranking_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    packet_schema_version text NOT NULL,
    packet jsonb NOT NULL,
    packet_hash text NOT NULL,
    estimated_tokens integer NOT NULL CHECK (estimated_tokens >= 0),
    section_counts jsonb NOT NULL,
    missing_sections text[] NOT NULL,
    truncated_sections text[] NOT NULL,
    PRIMARY KEY (llm_ranking_run_id, instrument_id),
    UNIQUE (llm_ranking_run_id, packet_hash)
);

CREATE TABLE IF NOT EXISTS analytics.llm_evidence_link (
    evidence_link_id uuid PRIMARY KEY,
    llm_ranking_run_id uuid NOT NULL,
    instrument_id uuid NOT NULL,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    source_kind text NOT NULL,
    entity_key text NOT NULL,
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz,
    event_at timestamptz,
    FOREIGN KEY (llm_ranking_run_id, instrument_id)
        REFERENCES analytics.llm_evidence_packet(llm_ranking_run_id, instrument_id),
    UNIQUE (llm_ranking_run_id, instrument_id, source_kind, entity_key)
);

CREATE TABLE IF NOT EXISTS analytics.llm_call_attempt (
    llm_call_attempt_id uuid PRIMARY KEY,
    llm_ranking_run_id uuid NOT NULL
        REFERENCES analytics.llm_ranking_run(llm_ranking_run_id),
    call_stage text NOT NULL CHECK (call_stage IN ('INSTRUMENT_BATCH', 'FINAL_RANK')),
    batch_no integer NOT NULL CHECK (batch_no >= 0),
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    input_hash text NOT NULL,
    output_hash text,
    prompt_version text NOT NULL,
    deployment text NOT NULL,
    api_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('SUCCEEDED', 'FAILED')),
    http_status integer,
    error_code text,
    input_tokens integer CHECK (input_tokens IS NULL OR input_tokens >= 0),
    output_tokens integer CHECK (output_tokens IS NULL OR output_tokens >= 0),
    total_tokens integer CHECK (total_tokens IS NULL OR total_tokens >= 0),
    started_at timestamptz NOT NULL,
    finished_at timestamptz NOT NULL,
    UNIQUE (llm_ranking_run_id, call_stage, batch_no, attempt_no),
    CHECK (started_at <= finished_at),
    CHECK (
        (status = 'SUCCEEDED' AND output_hash IS NOT NULL AND error_code IS NULL)
        OR (status = 'FAILED' AND error_code IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS analytics.llm_instrument_assessment (
    llm_ranking_run_id uuid NOT NULL,
    instrument_id uuid NOT NULL,
    batch_no integer NOT NULL CHECK (batch_no >= 0),
    first_stage_rank integer NOT NULL CHECK (first_stage_rank > 0),
    score numeric(8, 4) NOT NULL CHECK (score BETWEEN 0 AND 100),
    sub_scores jsonb NOT NULL,
    evidence_quality text NOT NULL CHECK (
        evidence_quality IN ('HIGH', 'MEDIUM', 'LOW')
    ),
    uncertainty text NOT NULL CHECK (uncertainty IN ('LOW', 'MEDIUM', 'HIGH')),
    reason_codes text[] NOT NULL,
    rationale text NOT NULL,
    output_hash text NOT NULL,
    PRIMARY KEY (llm_ranking_run_id, instrument_id),
    UNIQUE (llm_ranking_run_id, first_stage_rank),
    FOREIGN KEY (llm_ranking_run_id, instrument_id)
        REFERENCES analytics.llm_evidence_packet(llm_ranking_run_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS selection.llm_preselection_run (
    run_id uuid PRIMARY KEY,
    llm_ranking_run_id uuid NOT NULL UNIQUE
        REFERENCES analytics.llm_ranking_run(llm_ranking_run_id),
    price_session_date date NOT NULL,
    cutoff_at timestamptz NOT NULL,
    generated_at timestamptz NOT NULL,
    valid_until timestamptz,
    policy_version text NOT NULL,
    selection_type text NOT NULL DEFAULT 'LLM_PRESELECTION'
        CHECK (selection_type = 'LLM_PRESELECTION'),
    requested_count integer NOT NULL DEFAULT 20 CHECK (requested_count = 20),
    selected_count integer NOT NULL CHECK (selected_count >= 0 AND selected_count <= 20),
    status text NOT NULL CHECK (status IN ('SUCCEEDED', 'SHORTFALL', 'FAILED')),
    failure_code text,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (status = 'SUCCEEDED' AND selected_count = 20 AND failure_code IS NULL)
        OR (status IN ('SHORTFALL', 'FAILED') AND failure_code IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS selection.llm_preselection_candidate (
    run_id uuid NOT NULL REFERENCES selection.llm_preselection_run(run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    position integer NOT NULL CHECK (position BETWEEN 1 AND 20),
    score numeric(8, 4) NOT NULL CHECK (score BETWEEN 0 AND 100),
    first_stage_rank integer NOT NULL CHECK (first_stage_rank > 0),
    final_rank integer NOT NULL CHECK (final_rank BETWEEN 1 AND 20),
    evidence_quality text NOT NULL CHECK (
        evidence_quality IN ('HIGH', 'MEDIUM', 'LOW')
    ),
    reason_codes text[] NOT NULL,
    symbol text NOT NULL,
    company_name text NOT NULL,
    sector text,
    PRIMARY KEY (run_id, instrument_id),
    UNIQUE (run_id, position),
    UNIQUE (run_id, final_rank)
);

CREATE TABLE IF NOT EXISTS selection.llm_preselection_evidence (
    run_id uuid NOT NULL,
    instrument_id uuid NOT NULL,
    evidence_link_id uuid NOT NULL REFERENCES analytics.llm_evidence_link(evidence_link_id),
    priority integer NOT NULL CHECK (priority > 0),
    PRIMARY KEY (run_id, instrument_id, evidence_link_id),
    UNIQUE (run_id, instrument_id, priority),
    FOREIGN KEY (run_id, instrument_id)
        REFERENCES selection.llm_preselection_candidate(run_id, instrument_id)
);

CREATE INDEX IF NOT EXISTS llm_ranking_run_latest
    ON analytics.llm_ranking_run(price_session_date DESC, finished_at DESC);
CREATE INDEX IF NOT EXISTS llm_preselection_run_latest
    ON selection.llm_preselection_run(
        price_session_date DESC, generated_at DESC, created_at DESC
    );
CREATE INDEX IF NOT EXISTS llm_evidence_link_snapshot
    ON analytics.llm_evidence_link(source_snapshot_id);

DO $$
DECLARE
    table_name text;
BEGIN
    FOREACH table_name IN ARRAY ARRAY[
        'llm_ranking_run',
        'llm_evidence_packet',
        'llm_evidence_link',
        'llm_call_attempt',
        'llm_instrument_assessment'
    ]
    LOOP
        EXECUTE format(
            'DROP TRIGGER IF EXISTS %I_immutable ON analytics.%I',
            table_name,
            table_name
        );
        EXECUTE format(
            'CREATE TRIGGER %I_immutable BEFORE UPDATE OR DELETE ON analytics.%I '
            'FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_analytics_row()',
            table_name,
            table_name
        );
    END LOOP;
END
$$;

DROP TRIGGER IF EXISTS llm_preselection_run_immutable
    ON selection.llm_preselection_run;
CREATE TRIGGER llm_preselection_run_immutable
BEFORE UPDATE OR DELETE ON selection.llm_preselection_run
FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_analytics_row();

DROP TRIGGER IF EXISTS llm_preselection_candidate_immutable
    ON selection.llm_preselection_candidate;
CREATE TRIGGER llm_preselection_candidate_immutable
BEFORE UPDATE OR DELETE ON selection.llm_preselection_candidate
FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_analytics_row();

DROP TRIGGER IF EXISTS llm_preselection_evidence_immutable
    ON selection.llm_preselection_evidence;
CREATE TRIGGER llm_preselection_evidence_immutable
BEFORE UPDATE OR DELETE ON selection.llm_preselection_evidence
FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_analytics_row();

INSERT INTO ops.schema_migration(version)
VALUES ('022_llm_preselection')
ON CONFLICT (version) DO NOTHING;
