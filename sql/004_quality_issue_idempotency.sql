WITH ranked AS (
    SELECT
        issue_id,
        row_number() OVER (
            PARTITION BY
                ingestion_run_id,
                dataset_code,
                coalesce(entity_key, ''),
                rule_code
            ORDER BY detected_at, issue_id
        ) AS duplicate_rank
    FROM ops.data_quality_issue
)
DELETE FROM ops.data_quality_issue issue
USING ranked
WHERE issue.issue_id = ranked.issue_id
  AND ranked.duplicate_rank > 1;

CREATE UNIQUE INDEX IF NOT EXISTS data_quality_issue_run_entity_rule_unique
    ON ops.data_quality_issue(
        ingestion_run_id,
        dataset_code,
        coalesce(entity_key, ''),
        rule_code
    );

INSERT INTO ops.schema_migration(version)
VALUES ('004_quality_issue_idempotency')
ON CONFLICT (version) DO NOTHING;
