ALTER TABLE analytics.model_version
    ADD COLUMN IF NOT EXISTS model_purpose text,
    ADD COLUMN IF NOT EXISTS return_policy text;

UPDATE analytics.model_version
   SET model_purpose = 'SHORT_5D'
 WHERE model_purpose IS NULL;

UPDATE analytics.model_version
   SET return_policy = 'PRICE_RETURN'
 WHERE return_policy IS NULL;

ALTER TABLE analytics.model_version
    ALTER COLUMN model_purpose SET NOT NULL,
    ALTER COLUMN model_purpose SET DEFAULT 'SHORT_5D',
    ALTER COLUMN return_policy SET NOT NULL,
    ALTER COLUMN return_policy SET DEFAULT 'PRICE_RETURN';

ALTER TABLE analytics.model_version
    DROP CONSTRAINT IF EXISTS model_version_model_name_version_config_hash_export_run_id_key;

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'model_version_identity_key'
           AND conrelid = 'analytics.model_version'::regclass
    ) THEN
        ALTER TABLE analytics.model_version
            ADD CONSTRAINT model_version_identity_key UNIQUE (
                model_name,
                version,
                config_hash,
                export_run_id,
                model_purpose,
                return_policy
            );
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS model_version_purpose
    ON analytics.model_version(model_purpose, created_at DESC, model_version_id);

CREATE INDEX IF NOT EXISTS selection_run_latest_by_date
    ON selection.selection_run(
        price_session_date DESC,
        generated_at DESC,
        created_at DESC,
        selection_run_id DESC
    )
    WHERE status = 'SUCCEEDED';

INSERT INTO ops.schema_migration(version)
VALUES ('018_multi_model_support')
ON CONFLICT (version) DO NOTHING;
