CREATE TABLE IF NOT EXISTS ref.exchange_session (
    calendar_version text NOT NULL,
    exchange_mic text NOT NULL,
    session_date date NOT NULL,
    open_at timestamptz NOT NULL,
    close_at timestamptz NOT NULL,
    is_early_close boolean NOT NULL,
    status text NOT NULL CHECK (status IN ('OPEN', 'CLOSED', 'SPECIAL')),
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (calendar_version, exchange_mic, session_date),
    CHECK (open_at < close_at)
);

CREATE INDEX IF NOT EXISTS exchange_session_mic_date
    ON ref.exchange_session(exchange_mic, session_date DESC);

INSERT INTO ops.schema_migration(version)
VALUES ('011_reference_calendar')
ON CONFLICT (version) DO NOTHING;
