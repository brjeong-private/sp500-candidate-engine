ALTER TABLE ops.source_snapshot
    DROP CONSTRAINT IF EXISTS source_snapshot_source_id_dataset_code_content_hash_key;

CREATE UNIQUE INDEX IF NOT EXISTS source_snapshot_coverage_content_unique
    ON ops.source_snapshot(
        source_id,
        dataset_code,
        coverage_start,
        coverage_end,
        content_hash
    );

INSERT INTO ops.schema_migration(version)
VALUES ('003_snapshot_coverage_identity')
ON CONFLICT (version) DO NOTHING;
