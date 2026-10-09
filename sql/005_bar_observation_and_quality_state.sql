CREATE TABLE IF NOT EXISTS market.daily_bar_observation (
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    instrument_id uuid NOT NULL,
    session_date date NOT NULL,
    source_id bigint NOT NULL,
    revision_no integer NOT NULL,
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (
        source_snapshot_id,
        instrument_id,
        session_date,
        source_id,
        revision_no
    ),
    FOREIGN KEY (instrument_id, session_date, source_id, revision_no)
        REFERENCES market.daily_bar(instrument_id, session_date, source_id, revision_no)
);

CREATE INDEX IF NOT EXISTS daily_bar_observation_snapshot_date
    ON market.daily_bar_observation(source_snapshot_id, session_date);

INSERT INTO market.daily_bar_observation(
    source_snapshot_id,
    instrument_id,
    session_date,
    source_id,
    revision_no,
    observed_at
)
SELECT
    source_snapshot_id,
    instrument_id,
    session_date,
    source_id,
    revision_no,
    observed_at
FROM market.daily_bar
ON CONFLICT DO NOTHING;

ALTER TABLE ops.data_quality_issue
    ADD COLUMN IF NOT EXISTS status text NOT NULL DEFAULT 'ACTIVE',
    ADD COLUMN IF NOT EXISTS last_seen_at timestamptz,
    ADD COLUMN IF NOT EXISTS resolved_at timestamptz;

UPDATE ops.data_quality_issue
SET last_seen_at = detected_at
WHERE last_seen_at IS NULL;

ALTER TABLE ops.data_quality_issue
    ALTER COLUMN last_seen_at SET NOT NULL;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'data_quality_issue_status_check'
          AND conrelid = 'ops.data_quality_issue'::regclass
    ) THEN
        ALTER TABLE ops.data_quality_issue
            ADD CONSTRAINT data_quality_issue_status_check
            CHECK (status IN ('ACTIVE', 'RESOLVED'));
    END IF;
END
$$;

INSERT INTO ops.schema_migration(version)
VALUES ('005_bar_observation_and_quality_state')
ON CONFLICT (version) DO NOTHING;
