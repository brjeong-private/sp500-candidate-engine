CREATE TABLE IF NOT EXISTS analytics.feature_definition_version (
    feature_definition_version_id uuid PRIMARY KEY,
    name text NOT NULL,
    version text NOT NULL,
    stage text NOT NULL CHECK (stage IN ('RAW', 'PROCESSED')),
    feature_names text[] NOT NULL,
    expected_dimension integer NOT NULL CHECK (expected_dimension > 0),
    expression_hash text NOT NULL,
    lookback_sessions integer NOT NULL CHECK (lookback_sessions >= 0),
    handler_config jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version, stage),
    CHECK (cardinality(feature_names) = expected_dimension)
);

CREATE TABLE IF NOT EXISTS analytics.processor_version (
    processor_version_id uuid PRIMARY KEY,
    name text NOT NULL,
    version text NOT NULL,
    processor_kind text NOT NULL CHECK (
        processor_kind IN ('LEARN', 'INFER', 'FEATURE')
    ),
    config jsonb NOT NULL,
    fit_execution_context_id uuid NOT NULL
        REFERENCES ops.execution_context(execution_context_id),
    fit_start date NOT NULL,
    fit_end date NOT NULL,
    artifact_uri text NOT NULL,
    artifact_hash text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version),
    CHECK (fit_start <= fit_end)
);

CREATE TABLE IF NOT EXISTS analytics.feature_run (
    feature_run_id uuid PRIMARY KEY,
    export_run_id uuid NOT NULL
        REFERENCES analytics.qlib_export_run(export_run_id),
    feature_definition_version_id uuid NOT NULL
        REFERENCES analytics.feature_definition_version(feature_definition_version_id),
    processor_version_id uuid
        REFERENCES analytics.processor_version(processor_version_id),
    parent_feature_run_id uuid
        REFERENCES analytics.feature_run(feature_run_id),
    stage text NOT NULL CHECK (stage IN ('RAW', 'PROCESSED')),
    code_version text NOT NULL,
    status text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    idempotency_key text NOT NULL UNIQUE,
    value_count bigint NOT NULL DEFAULT 0 CHECK (value_count >= 0),
    error_message text,
    computed_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (stage = 'RAW' AND processor_version_id IS NULL)
        OR (stage = 'PROCESSED' AND processor_version_id IS NOT NULL)
    )
);

CREATE TABLE IF NOT EXISTS analytics.feature_value (
    feature_run_id uuid NOT NULL
        REFERENCES analytics.feature_run(feature_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    session_date date NOT NULL,
    values_real real[] NOT NULL,
    value_count integer NOT NULL CHECK (value_count > 0),
    missing_count integer NOT NULL CHECK (
        missing_count >= 0 AND missing_count <= value_count
    ),
    missing_bitmap bytea,
    quality_status text NOT NULL,
    PRIMARY KEY (feature_run_id, instrument_id, session_date),
    CHECK (cardinality(values_real) = value_count)
);

CREATE INDEX IF NOT EXISTS feature_value_instrument_date
    ON analytics.feature_value(feature_run_id, instrument_id, session_date);

CREATE TABLE IF NOT EXISTS analytics.label_definition_version (
    label_definition_version_id uuid PRIMARY KEY,
    name text NOT NULL,
    version text NOT NULL,
    entry_rule jsonb NOT NULL,
    exit_rule jsonb NOT NULL,
    benchmark_code text NOT NULL,
    corporate_action_policy text NOT NULL,
    boundary_policy jsonb NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (name, version)
);

CREATE TABLE IF NOT EXISTS analytics.label_run (
    label_run_id uuid PRIMARY KEY,
    execution_context_id uuid NOT NULL
        REFERENCES ops.execution_context(execution_context_id),
    universe_version_id uuid NOT NULL
        REFERENCES ref.universe_version(universe_version_id),
    label_definition_version_id uuid NOT NULL
        REFERENCES analytics.label_definition_version(label_definition_version_id),
    code_version text NOT NULL,
    boundary_policy jsonb NOT NULL,
    status text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    idempotency_key text NOT NULL UNIQUE,
    error_message text,
    created_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);

CREATE TABLE IF NOT EXISTS analytics.daily_label (
    label_run_id uuid NOT NULL REFERENCES analytics.label_run(label_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    anchor_session_date date NOT NULL,
    entry_session_date date NOT NULL,
    exit_session_date date NOT NULL,
    raw_return real,
    benchmark_return real,
    label_value real,
    quality_status text NOT NULL,
    PRIMARY KEY (label_run_id, instrument_id, anchor_session_date),
    CHECK (anchor_session_date < entry_session_date),
    CHECK (entry_session_date <= exit_session_date),
    CHECK (
        (quality_status = 'OK' AND label_value IS NOT NULL)
        OR quality_status <> 'OK'
    )
);

CREATE INDEX IF NOT EXISTS daily_label_instrument_anchor
    ON analytics.daily_label(instrument_id, anchor_session_date);

INSERT INTO ops.schema_migration(version)
VALUES ('013_analytics_features_labels')
ON CONFLICT (version) DO NOTHING;
