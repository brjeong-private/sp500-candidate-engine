CREATE TABLE IF NOT EXISTS event.news_event_classification (
    classification_id uuid PRIMARY KEY,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    event_revision_id uuid NOT NULL REFERENCES event.event_revision(event_revision_id),
    status text NOT NULL CHECK (status IN ('SUCCEEDED', 'MISSING', 'FAILED')),
    input_hash text NOT NULL,
    prompt_version text NOT NULL,
    deployment text NOT NULL,
    structured_output jsonb,
    output_hash text,
    error_code text,
    classified_at timestamptz NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (
        source_snapshot_id, event_revision_id, input_hash, prompt_version, deployment
    ),
    CHECK (
        (status = 'SUCCEEDED' AND structured_output IS NOT NULL AND output_hash IS NOT NULL
            AND error_code IS NULL)
        OR
        (status IN ('MISSING', 'FAILED') AND structured_output IS NULL
            AND output_hash IS NULL AND error_code IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS analytics.experiment_readiness_assessment (
    readiness_assessment_id uuid PRIMARY KEY,
    execution_context_id uuid NOT NULL
        REFERENCES ops.execution_context(execution_context_id),
    experiment_code text NOT NULL CHECK (experiment_code IN ('E2', 'E3', 'E4', 'E5', 'E6')),
    status text NOT NULL CHECK (status IN ('READY', 'BLOCKED')),
    blocking_reasons text[] NOT NULL,
    evidence jsonb NOT NULL,
    assessed_at timestamptz NOT NULL,
    code_version text NOT NULL,
    UNIQUE (execution_context_id, experiment_code, assessed_at, code_version),
    CHECK (
        (status = 'READY' AND cardinality(blocking_reasons) = 0)
        OR (status = 'BLOCKED' AND cardinality(blocking_reasons) > 0)
    )
);

CREATE OR REPLACE FUNCTION ops.reject_immutable_analytics_row()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    RAISE EXCEPTION '% is append-only', TG_TABLE_NAME;
END
$$;

DROP TRIGGER IF EXISTS news_event_classification_immutable
    ON event.news_event_classification;
CREATE TRIGGER news_event_classification_immutable
BEFORE UPDATE OR DELETE ON event.news_event_classification
FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_analytics_row();

DROP TRIGGER IF EXISTS experiment_readiness_assessment_immutable
    ON analytics.experiment_readiness_assessment;
CREATE TRIGGER experiment_readiness_assessment_immutable
BEFORE UPDATE OR DELETE ON analytics.experiment_readiness_assessment
FOR EACH ROW EXECUTE FUNCTION ops.reject_immutable_analytics_row();

INSERT INTO ops.schema_migration(version)
VALUES ('019_advanced_feature_availability')
ON CONFLICT (version) DO NOTHING;
