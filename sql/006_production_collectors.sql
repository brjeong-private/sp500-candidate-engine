CREATE SCHEMA IF NOT EXISTS fundamental;
CREATE SCHEMA IF NOT EXISTS event;

CREATE TABLE IF NOT EXISTS ops.ingestion_checkpoint (
    source_id bigint NOT NULL REFERENCES ops.data_source(source_id),
    dataset_code text NOT NULL,
    partition_key text NOT NULL DEFAULT 'default',
    cursor_value text,
    last_source_at timestamptz,
    last_success_at timestamptz NOT NULL,
    updated_by_run_id uuid NOT NULL REFERENCES ops.ingestion_run(ingestion_run_id),
    PRIMARY KEY (source_id, dataset_code, partition_key)
);

CREATE TABLE IF NOT EXISTS ref.instrument_state (
    instrument_state_id uuid PRIMARY KEY,
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    primary_exchange text,
    status text NOT NULL,
    valid_from date NOT NULL,
    valid_to date,
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    revision_no integer NOT NULL CHECK (revision_no > 0),
    UNIQUE (instrument_id, valid_from, revision_no),
    CHECK (valid_to IS NULL OR valid_from <= valid_to)
);

CREATE TABLE IF NOT EXISTS market.corporate_action (
    action_id uuid PRIMARY KEY,
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    source_id bigint NOT NULL REFERENCES ops.data_source(source_id),
    source_action_id text NOT NULL,
    action_type text NOT NULL CHECK (action_type IN ('DIVIDEND', 'SPLIT')),
    revision_no integer NOT NULL CHECK (revision_no > 0),
    effective_date date NOT NULL,
    declaration_date date,
    record_date date,
    pay_date date,
    cash_amount numeric(20, 8),
    currency text,
    split_from numeric(20, 8),
    split_to numeric(20, 8),
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    origin_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    payload_hash text NOT NULL,
    metadata jsonb NOT NULL,
    UNIQUE (source_id, source_action_id, revision_no)
);

CREATE INDEX IF NOT EXISTS corporate_action_instrument_date
    ON market.corporate_action(instrument_id, effective_date DESC);

CREATE TABLE IF NOT EXISTS market.corporate_action_observation (
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    action_id uuid NOT NULL REFERENCES market.corporate_action(action_id),
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (source_snapshot_id, action_id)
);

CREATE TABLE IF NOT EXISTS event.market_event (
    event_id uuid PRIMARY KEY,
    source_id bigint NOT NULL REFERENCES ops.data_source(source_id),
    source_event_id text NOT NULL,
    event_type text NOT NULL,
    canonical_key text NOT NULL,
    created_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (source_id, source_event_id)
);

CREATE TABLE IF NOT EXISTS event.event_revision (
    event_revision_id uuid PRIMARY KEY,
    event_id uuid NOT NULL REFERENCES event.market_event(event_id),
    revision_no integer NOT NULL CHECK (revision_no > 0),
    title text NOT NULL,
    source_url text,
    status text,
    scheduled_at timestamptz,
    published_at timestamptz,
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    origin_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    payload_hash text NOT NULL,
    metadata jsonb NOT NULL,
    UNIQUE (event_id, revision_no)
);

CREATE TABLE IF NOT EXISTS event.event_revision_observation (
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    event_revision_id uuid NOT NULL REFERENCES event.event_revision(event_revision_id),
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (source_snapshot_id, event_revision_id)
);

CREATE TABLE IF NOT EXISTS event.event_instrument (
    event_id uuid NOT NULL REFERENCES event.market_event(event_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    relation_type text NOT NULL DEFAULT 'PRIMARY',
    PRIMARY KEY (event_id, instrument_id)
);

CREATE TABLE IF NOT EXISTS fundamental.sec_filing (
    filing_id uuid PRIMARY KEY,
    issuer_id uuid NOT NULL REFERENCES ref.issuer(issuer_id),
    accession_no text NOT NULL UNIQUE,
    form_type text NOT NULL,
    period_end date,
    filed_date date NOT NULL,
    accepted_at timestamptz NOT NULL,
    primary_document_url text,
    is_amendment boolean NOT NULL,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id)
);

CREATE TABLE IF NOT EXISTS fundamental.fact (
    fact_id uuid PRIMARY KEY,
    filing_id uuid NOT NULL REFERENCES fundamental.sec_filing(filing_id),
    issuer_id uuid NOT NULL REFERENCES ref.issuer(issuer_id),
    taxonomy text NOT NULL,
    concept text NOT NULL,
    unit text NOT NULL,
    period_start date,
    period_end date NOT NULL,
    value_numeric numeric,
    decimals integer,
    fiscal_year integer,
    fiscal_period text,
    frame text,
    context_hash text NOT NULL UNIQUE,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL
);

INSERT INTO ops.schema_migration(version)
VALUES ('006_production_collectors')
ON CONFLICT (version) DO NOTHING;
