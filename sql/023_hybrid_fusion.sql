ALTER TABLE selection.selection_run
    ADD COLUMN IF NOT EXISTS policy_hash text,
    ADD COLUMN IF NOT EXISTS payload_hash text;

ALTER TABLE analytics.llm_ranking_run ADD COLUMN IF NOT EXISTS policy_hash text;
ALTER TABLE analytics.llm_instrument_assessment
    ALTER COLUMN score DROP NOT NULL,
    ADD COLUMN IF NOT EXISTS criterion_evidence jsonb NOT NULL DEFAULT '[]'::jsonb,
    ADD COLUMN IF NOT EXISTS missing_reasons jsonb NOT NULL DEFAULT '{}'::jsonb,
    ADD COLUMN IF NOT EXISTS weight_denominator integer,
    ADD COLUMN IF NOT EXISTS supported_count integer;
ALTER TABLE analytics.llm_call_attempt ADD COLUMN IF NOT EXISTS response_output jsonb;
ALTER TABLE analytics.llm_call_attempt
    ADD COLUMN IF NOT EXISTS cache_source_attempt_id uuid
        REFERENCES analytics.llm_call_attempt(llm_call_attempt_id);

CREATE TABLE IF NOT EXISTS analytics.llm_screening_decision (
    llm_ranking_run_id uuid NOT NULL REFERENCES analytics.llm_ranking_run(llm_ranking_run_id),
    issuer_id uuid NOT NULL REFERENCES ref.issuer(issuer_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    decision jsonb NOT NULL,
    PRIMARY KEY (llm_ranking_run_id, issuer_id)
);

CREATE TABLE IF NOT EXISTS selection.fusion_run (
    fusion_run_id uuid PRIMARY KEY,
    execution_context_id uuid NOT NULL REFERENCES ops.execution_context(execution_context_id),
    quant_selection_run_id uuid REFERENCES selection.selection_run(selection_run_id),
    llm_preselection_run_id uuid REFERENCES selection.llm_preselection_run(run_id),
    price_session_date date NOT NULL,
    cutoff_at timestamptz NOT NULL,
    generated_at timestamptz NOT NULL,
    model_purpose text NOT NULL DEFAULT 'MEDIUM_20D' CHECK (model_purpose = 'MEDIUM_20D'),
    selection_type text NOT NULL DEFAULT 'FUSION' CHECK (selection_type = 'FUSION'),
    policy_version text NOT NULL,
    config_hash text NOT NULL,
    rrf_k integer NOT NULL CHECK (rrf_k > 0),
    requested_count integer NOT NULL DEFAULT 20 CHECK (requested_count = 20),
    selected_count integer NOT NULL CHECK (selected_count BETWEEN 0 AND 20),
    union_count integer NOT NULL CHECK (union_count BETWEEN 0 AND 40),
    status text NOT NULL CHECK (status IN ('SUCCEEDED', 'SHORTFALL', 'FAILED')),
    failure_code text,
    sector_cap_relaxed boolean NOT NULL,
    provenance jsonb NOT NULL,
    idempotency_key text NOT NULL UNIQUE,
    payload_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (status = 'SUCCEEDED' AND selected_count = 20 AND failure_code IS NULL
         AND quant_selection_run_id IS NOT NULL AND llm_preselection_run_id IS NOT NULL)
        OR (status IN ('SHORTFALL', 'FAILED') AND failure_code IS NOT NULL)
    ),
    CHECK (status <> 'FAILED' OR selected_count = 0)
);

CREATE TABLE IF NOT EXISTS selection.fusion_candidate (
    fusion_run_id uuid NOT NULL REFERENCES selection.fusion_run(fusion_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    issuer_id uuid NOT NULL REFERENCES ref.issuer(issuer_id),
    position integer NOT NULL CHECK (position BETWEEN 1 AND 20),
    rrf_numerator bigint NOT NULL CHECK (rrf_numerator > 0),
    rrf_denominator bigint NOT NULL CHECK (rrf_denominator > 0),
    candidate jsonb NOT NULL,
    PRIMARY KEY (fusion_run_id, instrument_id),
    UNIQUE (fusion_run_id, issuer_id),
    UNIQUE (fusion_run_id, position)
);

CREATE TABLE IF NOT EXISTS selection.fusion_audit (
    fusion_run_id uuid NOT NULL REFERENCES selection.fusion_run(fusion_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    decision jsonb NOT NULL,
    PRIMARY KEY (fusion_run_id, instrument_id)
);

CREATE INDEX IF NOT EXISTS fusion_run_latest
    ON selection.fusion_run(price_session_date DESC, generated_at DESC, fusion_run_id DESC);

DO $$
DECLARE
    qualified_name text;
BEGIN
    FOREACH qualified_name IN ARRAY ARRAY[
        'analytics.llm_screening_decision',
        'selection.fusion_run', 'selection.fusion_candidate', 'selection.fusion_audit'
    ]
    LOOP
        EXECUTE format('DROP TRIGGER IF EXISTS hybrid_immutable ON %s', qualified_name);
        EXECUTE format(
            'CREATE TRIGGER hybrid_immutable BEFORE UPDATE OR DELETE ON %s '
            'FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_analytics_row()', qualified_name
        );
    END LOOP;
END
$$;

INSERT INTO ops.schema_migration(version) VALUES ('023_hybrid_fusion')
ON CONFLICT (version) DO NOTHING;
