ALTER TABLE ops.source_snapshot
    ADD COLUMN IF NOT EXISTS availability_basis text;

UPDATE ops.source_snapshot
SET availability_basis = CASE dataset_code
    WHEN 'sp500_universe' THEN 'WIKIPEDIA_REVISION_TIMESTAMP'
    WHEN 'daily_bar' THEN 'ASSUMED_16_15_AMERICA_NEW_YORK'
    ELSE 'UNSPECIFIED'
END
WHERE availability_basis IS NULL;

ALTER TABLE ops.source_snapshot
    ALTER COLUMN availability_basis SET NOT NULL;

INSERT INTO ops.schema_migration(version)
VALUES ('002_snapshot_availability_basis')
ON CONFLICT (version) DO NOTHING;
