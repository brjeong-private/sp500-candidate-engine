ALTER TABLE ops.process_run DROP CONSTRAINT IF EXISTS process_run_process_type_check;
ALTER TABLE ops.process_run ADD CONSTRAINT process_run_process_type_check
    CHECK (process_type IN ('DAILY', 'RANGE', 'BACKFILL', 'BACKFILL_RETRY'));
ALTER TABLE ops.process_run ADD COLUMN IF NOT EXISTS parent_process_run_id uuid
    REFERENCES ops.process_run(process_run_id);
CREATE INDEX IF NOT EXISTS process_run_parent ON ops.process_run(parent_process_run_id);

-- Ownership and full API lifecycle are separate from the engine's collection lifecycle.
CREATE TABLE IF NOT EXISTS ops.backend_pipeline_request (
    process_run_id uuid PRIMARY KEY REFERENCES ops.process_run(process_run_id),
    mode text NOT NULL CHECK (mode IN ('DAILY', 'RANGE', 'BACKFILL')),
    status text NOT NULL CHECK (
        status IN ('PENDING', 'RUNNING', 'SUCCEEDED', 'PARTIAL_SUCCESS', 'FAILED')
    ),
    request_payload jsonb NOT NULL,
    failure_reason text,
    accepted_at timestamptz NOT NULL DEFAULT now(),
    finished_at timestamptz
);
CREATE UNIQUE INDEX IF NOT EXISTS backend_pipeline_single_active
    ON ops.backend_pipeline_request ((true)) WHERE status IN ('PENDING', 'RUNNING');
INSERT INTO ops.schema_migration(version) VALUES ('017_backend_requests')
ON CONFLICT (version) DO NOTHING;
