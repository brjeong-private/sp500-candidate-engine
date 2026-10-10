ALTER TABLE analytics.feature_run
    ADD COLUMN IF NOT EXISTS artifact_uri text,
    ADD COLUMN IF NOT EXISTS artifact_hash text;

ALTER TABLE analytics.label_run
    ADD COLUMN IF NOT EXISTS artifact_uri text,
    ADD COLUMN IF NOT EXISTS artifact_hash text;

CREATE TABLE IF NOT EXISTS analytics.model_version (
    model_version_id uuid PRIMARY KEY,
    model_name text NOT NULL,
    version text NOT NULL,
    export_run_id uuid NOT NULL
        REFERENCES analytics.qlib_export_run(export_run_id),
    training_feature_run_id uuid
        REFERENCES analytics.feature_run(feature_run_id),
    processor_version_id uuid
        REFERENCES analytics.processor_version(processor_version_id),
    label_run_id uuid
        REFERENCES analytics.label_run(label_run_id),
    config_hash text NOT NULL,
    split_spec jsonb NOT NULL,
    parameters jsonb NOT NULL,
    artifact_uri text NOT NULL,
    artifact_hash text NOT NULL,
    metrics jsonb NOT NULL,
    promotion_status text NOT NULL CHECK (
        promotion_status IN ('SHADOW', 'CHAMPION', 'REJECTED', 'ARCHIVED')
    ),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_name, version, config_hash, export_run_id)
);

CREATE TABLE IF NOT EXISTS analytics.scoring_run (
    scoring_run_id uuid PRIMARY KEY,
    session_date date NOT NULL,
    execution_context_id uuid NOT NULL
        REFERENCES ops.execution_context(execution_context_id),
    export_run_id uuid NOT NULL
        REFERENCES analytics.qlib_export_run(export_run_id),
    model_version_id uuid NOT NULL
        REFERENCES analytics.model_version(model_version_id),
    universe_version_id uuid NOT NULL
        REFERENCES ref.universe_version(universe_version_id),
    config_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    idempotency_key text NOT NULL UNIQUE,
    error_message text,
    computed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS analytics.daily_score (
    scoring_run_id uuid NOT NULL
        REFERENCES analytics.scoring_run(scoring_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    score real NOT NULL,
    rank_overall integer NOT NULL CHECK (rank_overall > 0),
    score_percentile real NOT NULL CHECK (
        score_percentile > 0 AND score_percentile <= 1
    ),
    rank_sector integer CHECK (rank_sector > 0),
    prediction_horizon integer NOT NULL CHECK (prediction_horizon > 0),
    quality_status text NOT NULL,
    PRIMARY KEY (scoring_run_id, instrument_id),
    UNIQUE (scoring_run_id, rank_overall)
);

CREATE INDEX IF NOT EXISTS scoring_run_session_model
    ON analytics.scoring_run(session_date DESC, model_version_id);

INSERT INTO ops.schema_migration(version)
VALUES ('014_models_scores')
ON CONFLICT (version) DO NOTHING;
