CREATE TABLE IF NOT EXISTS fundamental.sec_filing_observation (
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    filing_id uuid NOT NULL REFERENCES fundamental.sec_filing(filing_id),
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (source_snapshot_id, filing_id)
);

CREATE TABLE IF NOT EXISTS fundamental.fact_observation (
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    fact_id uuid NOT NULL REFERENCES fundamental.fact(fact_id),
    observed_at timestamptz NOT NULL,
    PRIMARY KEY (source_snapshot_id, fact_id)
);

INSERT INTO ops.schema_migration(version)
VALUES ('008_fundamental_observations')
ON CONFLICT (version) DO NOTHING;
