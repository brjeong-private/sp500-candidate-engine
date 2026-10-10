CREATE SCHEMA IF NOT EXISTS analytics;

CREATE TABLE IF NOT EXISTS analytics.qlib_export_run (
    export_run_id uuid PRIMARY KEY,
    execution_context_id uuid NOT NULL
        REFERENCES ops.execution_context(execution_context_id),
    universe_version_id uuid NOT NULL
        REFERENCES ref.universe_version(universe_version_id),
    start_date date NOT NULL,
    end_date date NOT NULL,
    adjustment_policy text NOT NULL CHECK (
        adjustment_policy IN ('SPLIT_ONLY', 'TOTAL_RETURN')
    ),
    qlib_version text NOT NULL,
    exporter_version text NOT NULL,
    status text NOT NULL CHECK (
        status IN ('RUNNING', 'SUCCEEDED', 'FAILED')
    ),
    idempotency_key text NOT NULL UNIQUE,
    artifact_uri text,
    artifact_hash text,
    row_count bigint NOT NULL DEFAULT 0 CHECK (row_count >= 0),
    error_message text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    CHECK (start_date <= end_date),
    CHECK (
        (status = 'SUCCEEDED' AND artifact_uri IS NOT NULL AND artifact_hash IS NOT NULL)
        OR status <> 'SUCCEEDED'
    )
);

CREATE TABLE IF NOT EXISTS analytics.qlib_calendar (
    export_run_id uuid NOT NULL
        REFERENCES analytics.qlib_export_run(export_run_id),
    session_date date NOT NULL,
    open_at timestamptz NOT NULL,
    close_at timestamptz NOT NULL,
    is_early_close boolean NOT NULL,
    PRIMARY KEY (export_run_id, session_date),
    CHECK (open_at < close_at)
);

CREATE TABLE IF NOT EXISTS analytics.qlib_instrument_span (
    export_run_id uuid NOT NULL
        REFERENCES analytics.qlib_export_run(export_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    symbol text NOT NULL,
    start_date date NOT NULL,
    end_date date NOT NULL,
    membership_source text NOT NULL,
    PRIMARY KEY (export_run_id, instrument_id),
    UNIQUE (export_run_id, symbol),
    CHECK (start_date <= end_date)
);

CREATE TABLE IF NOT EXISTS analytics.qlib_daily_value (
    export_run_id uuid NOT NULL
        REFERENCES analytics.qlib_export_run(export_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    session_date date NOT NULL,
    open real NOT NULL,
    high real NOT NULL,
    low real NOT NULL,
    close real NOT NULL,
    volume real NOT NULL,
    vwap real,
    factor real NOT NULL,
    change real,
    quality_status text NOT NULL,
    PRIMARY KEY (export_run_id, instrument_id, session_date),
    CHECK (open > 0 AND high > 0 AND low > 0 AND close > 0),
    CHECK (low <= high),
    CHECK (open BETWEEN low AND high),
    CHECK (close BETWEEN low AND high),
    CHECK (volume >= 0),
    CHECK (factor > 0)
);

CREATE INDEX IF NOT EXISTS qlib_daily_value_instrument_date
    ON analytics.qlib_daily_value(export_run_id, instrument_id, session_date);

INSERT INTO ops.schema_migration(version)
VALUES ('012_qlib_export')
ON CONFLICT (version) DO NOTHING;
