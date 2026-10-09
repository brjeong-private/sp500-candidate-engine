CREATE TABLE IF NOT EXISTS ops.process_run (
    process_run_id uuid PRIMARY KEY,
    process_type text NOT NULL CHECK (
        process_type IN ('DAILY', 'BACKFILL', 'BACKFILL_RETRY')
    ),
    status text NOT NULL CHECK (
        status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED')
    ),
    range_start date NOT NULL,
    range_end date NOT NULL,
    total_dates integer NOT NULL CHECK (total_dates >= 0),
    completed_dates integer NOT NULL DEFAULT 0 CHECK (completed_dates >= 0),
    success_dates integer NOT NULL DEFAULT 0 CHECK (success_dates >= 0),
    failed_dates integer NOT NULL DEFAULT 0 CHECK (failed_dates >= 0),
    retry_required_dates integer NOT NULL DEFAULT 0 CHECK (retry_required_dates >= 0),
    retry_attempted_dates integer NOT NULL DEFAULT 0 CHECK (retry_attempted_dates >= 0),
    started_at timestamptz NOT NULL,
    heartbeat_at timestamptz NOT NULL,
    finished_at timestamptz,
    log_uri text NOT NULL,
    metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
    CHECK (range_start <= range_end)
);

CREATE TABLE IF NOT EXISTS ops.process_date_status (
    process_run_id uuid NOT NULL REFERENCES ops.process_run(process_run_id),
    collection_date date NOT NULL,
    attempt_no integer NOT NULL CHECK (attempt_no > 0),
    event_type text NOT NULL CHECK (event_type IN ('COLLECTION', 'RETRY')),
    status text NOT NULL CHECK (
        status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')
    ),
    started_at timestamptz,
    finished_at timestamptz,
    duration_ms numeric,
    collected_item_count integer NOT NULL DEFAULT 0 CHECK (collected_item_count >= 0),
    collected_counts jsonb NOT NULL DEFAULT '{}'::jsonb,
    failure_reason text,
    retry_required boolean NOT NULL DEFAULT false,
    retry_status text NOT NULL DEFAULT 'NOT_REQUIRED' CHECK (
        retry_status IN ('NOT_REQUIRED', 'PENDING', 'RUNNING', 'SUCCEEDED', 'FAILED')
    ),
    completed boolean NOT NULL DEFAULT false,
    updated_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (process_run_id, collection_date, attempt_no)
);

CREATE INDEX IF NOT EXISTS process_date_retry_queue
    ON ops.process_date_status(process_run_id, collection_date, retry_status)
    WHERE retry_required;

INSERT INTO ops.schema_migration(version)
VALUES ('007_process_tracking')
ON CONFLICT (version) DO NOTHING;
