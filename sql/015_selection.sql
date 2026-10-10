CREATE SCHEMA IF NOT EXISTS selection;

CREATE TABLE IF NOT EXISTS selection.selection_run (
    selection_run_id uuid PRIMARY KEY,
    selection_type text NOT NULL CHECK (selection_type IN ('QUANTITATIVE')),
    price_session_date date NOT NULL,
    cutoff_at timestamptz NOT NULL,
    generated_at timestamptz NOT NULL,
    valid_until timestamptz,
    scoring_run_id uuid NOT NULL
        REFERENCES analytics.scoring_run(scoring_run_id),
    policy_version text NOT NULL,
    requested_count integer NOT NULL CHECK (
        requested_count BETWEEN 5 AND 10
    ),
    selected_count integer NOT NULL CHECK (
        selected_count BETWEEN 0 AND requested_count
    ),
    status text NOT NULL CHECK (status IN ('RUNNING', 'SUCCEEDED', 'SHORTFALL', 'FAILED')),
    shortfall_reason text,
    idempotency_key text NOT NULL UNIQUE,
    created_at timestamptz NOT NULL DEFAULT now(),
    CHECK (
        (status = 'SUCCEEDED' AND selected_count BETWEEN 5 AND 10)
        OR status <> 'SUCCEEDED'
    )
);

CREATE TABLE IF NOT EXISTS selection.candidate (
    selection_run_id uuid NOT NULL
        REFERENCES selection.selection_run(selection_run_id),
    instrument_id uuid NOT NULL REFERENCES ref.instrument(instrument_id),
    position integer NOT NULL CHECK (position BETWEEN 1 AND 10),
    score real NOT NULL,
    rank_overall integer NOT NULL CHECK (rank_overall > 0),
    score_percentile real NOT NULL CHECK (
        score_percentile > 0 AND score_percentile <= 1
    ),
    rank_sector integer CHECK (rank_sector > 0),
    quality_status text NOT NULL,
    latest_data_at timestamptz NOT NULL,
    PRIMARY KEY (selection_run_id, instrument_id),
    UNIQUE (selection_run_id, position)
);

CREATE TABLE IF NOT EXISTS selection.candidate_reason (
    candidate_reason_id uuid PRIMARY KEY,
    selection_run_id uuid NOT NULL,
    instrument_id uuid NOT NULL,
    reason_code text NOT NULL,
    priority integer NOT NULL CHECK (priority > 0),
    event_revision_id uuid REFERENCES event.event_revision(event_revision_id),
    reason_fingerprint text NOT NULL,
    reason_detail jsonb NOT NULL,
    FOREIGN KEY (selection_run_id, instrument_id)
        REFERENCES selection.candidate(selection_run_id, instrument_id),
    UNIQUE (selection_run_id, instrument_id, reason_fingerprint)
);

CREATE INDEX IF NOT EXISTS selection_run_price_date
    ON selection.selection_run(price_session_date DESC, status);

INSERT INTO ops.schema_migration(version)
VALUES ('015_selection')
ON CONFLICT (version) DO NOTHING;
