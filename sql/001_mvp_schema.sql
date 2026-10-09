CREATE SCHEMA IF NOT EXISTS ops;
CREATE SCHEMA IF NOT EXISTS ref;
CREATE SCHEMA IF NOT EXISTS market;

CREATE TABLE IF NOT EXISTS ops.schema_migration (
    version text PRIMARY KEY,
    applied_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.data_source (
    source_id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    base_url text NOT NULL,
    license_class text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.ingestion_run (
    ingestion_run_id uuid PRIMARY KEY,
    dataset_code text NOT NULL,
    target_date date NOT NULL,
    cutoff_at timestamptz NOT NULL,
    knowledge_mode text NOT NULL CHECK (
        knowledge_mode IN ('OPERATIONAL_REPLAY', 'HISTORICAL_RECONSTRUCTION')
    ),
    config_hash text NOT NULL,
    status text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'FAILED')),
    requested_count integer NOT NULL DEFAULT 0 CHECK (requested_count >= 0),
    received_count integer NOT NULL DEFAULT 0 CHECK (received_count >= 0),
    inserted_count integer NOT NULL DEFAULT 0 CHECK (inserted_count >= 0),
    error_count integer NOT NULL DEFAULT 0 CHECK (error_count >= 0),
    error_message text,
    started_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz,
    UNIQUE (dataset_code, target_date, config_hash)
);

CREATE TABLE IF NOT EXISTS ops.source_snapshot (
    source_snapshot_id uuid PRIMARY KEY,
    ingestion_run_id uuid NOT NULL REFERENCES ops.ingestion_run(ingestion_run_id),
    source_id bigint NOT NULL REFERENCES ops.data_source(source_id),
    dataset_code text NOT NULL,
    snapshot_kind text NOT NULL CHECK (snapshot_kind IN ('FULL', 'DELTA')),
    parent_snapshot_id uuid REFERENCES ops.source_snapshot(source_snapshot_id),
    coverage_start date NOT NULL,
    coverage_end date NOT NULL,
    sequence_no bigint NOT NULL DEFAULT 1 CHECK (sequence_no > 0),
    as_of_at timestamptz NOT NULL,
    fetched_at timestamptz NOT NULL,
    source_available_at timestamptz NOT NULL,
    storage_uri text NOT NULL,
    content_hash text NOT NULL,
    byte_size bigint NOT NULL CHECK (byte_size >= 0),
    license_class text NOT NULL,
    is_reconstruction boolean NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, dataset_code, content_hash),
    CHECK (coverage_start <= coverage_end)
);

CREATE TABLE IF NOT EXISTS ops.input_manifest (
    input_manifest_id uuid PRIMARY KEY,
    manifest_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.input_manifest_member (
    input_manifest_id uuid NOT NULL REFERENCES ops.input_manifest(input_manifest_id),
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    dataset_code text NOT NULL,
    precedence integer NOT NULL CHECK (precedence >= 0),
    lineage_role text NOT NULL CHECK (lineage_role IN ('BASELINE', 'DELTA', 'SINGLE')),
    PRIMARY KEY (input_manifest_id, source_snapshot_id)
);

CREATE TABLE IF NOT EXISTS ops.execution_context (
    execution_context_id uuid PRIMARY KEY,
    input_manifest_id uuid NOT NULL REFERENCES ops.input_manifest(input_manifest_id),
    cutoff_at timestamptz NOT NULL,
    knowledge_mode text NOT NULL CHECK (
        knowledge_mode IN ('OPERATIONAL_REPLAY', 'HISTORICAL_RECONSTRUCTION')
    ),
    code_version text NOT NULL,
    config_version text NOT NULL,
    context_hash text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ops.data_quality_issue (
    issue_id uuid PRIMARY KEY,
    ingestion_run_id uuid NOT NULL REFERENCES ops.ingestion_run(ingestion_run_id),
    dataset_code text NOT NULL,
    entity_key text,
    rule_code text NOT NULL,
    severity text NOT NULL CHECK (severity IN ('WARNING', 'ERROR', 'BLOCKING')),
    details jsonb NOT NULL,
    detected_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ref.issuer (
    issuer_id uuid PRIMARY KEY,
    cik text,
    legal_name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE UNIQUE INDEX IF NOT EXISTS issuer_cik_unique
    ON ref.issuer(cik) WHERE cik IS NOT NULL;

CREATE TABLE IF NOT EXISTS ref.instrument (
    instrument_id uuid PRIMARY KEY,
    issuer_id uuid NOT NULL REFERENCES ref.issuer(issuer_id),
    instrument_type text NOT NULL DEFAULT 'COMMON_STOCK',
    share_class text,
    currency text NOT NULL DEFAULT 'USD',
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ref.instrument_identifier (
    identifier_id uuid PRIMARY KEY,
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    id_type text NOT NULL,
    id_value text NOT NULL,
    valid_from date NOT NULL,
    valid_to date,
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    revision_no integer NOT NULL DEFAULT 1 CHECK (revision_no > 0),
    UNIQUE (id_type, id_value, valid_from, revision_no),
    CHECK (valid_to IS NULL OR valid_from <= valid_to)
);

CREATE TABLE IF NOT EXISTS ref.universe (
    universe_id uuid PRIMARY KEY,
    code text NOT NULL UNIQUE,
    name text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ref.universe_version (
    universe_version_id uuid PRIMARY KEY,
    universe_id uuid NOT NULL REFERENCES ref.universe(universe_id),
    provider_revision_id text NOT NULL,
    as_of_date date NOT NULL,
    announced_at timestamptz NOT NULL,
    effective_at timestamptz NOT NULL,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (universe_id, provider_revision_id)
);

CREATE TABLE IF NOT EXISTS ref.universe_member (
    universe_version_id uuid NOT NULL REFERENCES ref.universe_version(universe_version_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    symbol text NOT NULL,
    security_name text NOT NULL,
    sector text,
    sub_industry text,
    provider_symbol text NOT NULL,
    PRIMARY KEY (universe_version_id, instrument_id),
    UNIQUE (universe_version_id, symbol)
);

CREATE TABLE IF NOT EXISTS market.daily_bar (
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    session_date date NOT NULL,
    source_id bigint NOT NULL REFERENCES ops.data_source(source_id),
    revision_no integer NOT NULL CHECK (revision_no > 0),
    open numeric(20, 8) NOT NULL CHECK (open > 0),
    high numeric(20, 8) NOT NULL CHECK (high > 0),
    low numeric(20, 8) NOT NULL CHECK (low > 0),
    close numeric(20, 8) NOT NULL CHECK (close > 0),
    adjusted_close numeric(20, 8),
    volume bigint NOT NULL CHECK (volume >= 0),
    currency text NOT NULL DEFAULT 'USD',
    source_timestamp timestamptz NOT NULL,
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (instrument_id, session_date, source_id, revision_no),
    CHECK (low <= high),
    CHECK (open BETWEEN low AND high),
    CHECK (close BETWEEN low AND high)
);

CREATE INDEX IF NOT EXISTS daily_bar_instrument_date
    ON market.daily_bar(instrument_id, session_date DESC);

CREATE OR REPLACE FUNCTION ops.enforce_source_snapshot_fence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    run_target date;
    run_cutoff timestamptz;
    run_mode text;
BEGIN
    SELECT target_date, cutoff_at, knowledge_mode
      INTO run_target, run_cutoff, run_mode
      FROM ops.ingestion_run
     WHERE ingestion_run_id = NEW.ingestion_run_id;

    IF NEW.coverage_end > run_target THEN
        RAISE EXCEPTION 'temporal fence: snapshot coverage_end % exceeds target_date %',
            NEW.coverage_end, run_target;
    END IF;
    IF NEW.source_available_at > run_cutoff THEN
        RAISE EXCEPTION 'temporal fence: source_available_at % exceeds cutoff_at %',
            NEW.source_available_at, run_cutoff;
    END IF;
    IF run_mode = 'OPERATIONAL_REPLAY' AND NEW.fetched_at > run_cutoff THEN
        RAISE EXCEPTION 'temporal fence: fetched_at % exceeds operational cutoff_at %',
            NEW.fetched_at, run_cutoff;
    END IF;
    IF run_mode = 'HISTORICAL_RECONSTRUCTION' AND NOT NEW.is_reconstruction THEN
        RAISE EXCEPTION 'temporal fence: reconstruction run requires reconstruction snapshot';
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS source_snapshot_temporal_fence ON ops.source_snapshot;
CREATE TRIGGER source_snapshot_temporal_fence
BEFORE INSERT OR UPDATE ON ops.source_snapshot
FOR EACH ROW EXECUTE FUNCTION ops.enforce_source_snapshot_fence();

CREATE OR REPLACE FUNCTION market.enforce_daily_bar_fence()
RETURNS trigger
LANGUAGE plpgsql
AS $$
DECLARE
    run_target date;
    run_cutoff timestamptz;
    run_mode text;
BEGIN
    SELECT r.target_date, r.cutoff_at, r.knowledge_mode
      INTO run_target, run_cutoff, run_mode
      FROM ops.source_snapshot s
      JOIN ops.ingestion_run r ON r.ingestion_run_id = s.ingestion_run_id
     WHERE s.source_snapshot_id = NEW.source_snapshot_id;

    IF NEW.session_date > run_target THEN
        RAISE EXCEPTION 'temporal fence: bar session_date % exceeds target_date %',
            NEW.session_date, run_target;
    END IF;
    IF NEW.source_available_at > run_cutoff THEN
        RAISE EXCEPTION 'temporal fence: bar source_available_at % exceeds cutoff_at %',
            NEW.source_available_at, run_cutoff;
    END IF;
    IF run_mode = 'OPERATIONAL_REPLAY' AND NEW.observed_at > run_cutoff THEN
        RAISE EXCEPTION 'temporal fence: bar observed_at % exceeds operational cutoff_at %',
            NEW.observed_at, run_cutoff;
    END IF;
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS daily_bar_temporal_fence ON market.daily_bar;
CREATE TRIGGER daily_bar_temporal_fence
BEFORE INSERT OR UPDATE ON market.daily_bar
FOR EACH ROW EXECUTE FUNCTION market.enforce_daily_bar_fence();

INSERT INTO ops.schema_migration(version)
VALUES ('001_mvp_schema')
ON CONFLICT (version) DO NOTHING;
