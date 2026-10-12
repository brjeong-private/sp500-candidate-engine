ALTER TABLE ops.backend_pipeline_request
    ADD COLUMN IF NOT EXISTS idempotency_key text,
    ADD COLUMN IF NOT EXISTS request_hash text;

ALTER TABLE ops.backend_pipeline_request
    ALTER COLUMN idempotency_key DROP NOT NULL,
    ALTER COLUMN request_hash DROP NOT NULL;

ALTER TABLE ops.backend_pipeline_request
    DROP CONSTRAINT IF EXISTS backend_pipeline_idempotency_pair;
ALTER TABLE ops.backend_pipeline_request
    ADD CONSTRAINT backend_pipeline_idempotency_pair CHECK (
        (idempotency_key IS NULL) = (request_hash IS NULL)
    );

ALTER TABLE ops.backend_pipeline_request
    DROP CONSTRAINT IF EXISTS backend_pipeline_idempotency_key_format;
ALTER TABLE ops.backend_pipeline_request
    ADD CONSTRAINT backend_pipeline_idempotency_key_format CHECK (
        length(idempotency_key) BETWEEN 1 AND 128
        AND idempotency_key ~ '^[A-Za-z0-9][A-Za-z0-9._:-]*$'
    );

ALTER TABLE ops.backend_pipeline_request
    DROP CONSTRAINT IF EXISTS backend_pipeline_request_hash_format;
ALTER TABLE ops.backend_pipeline_request
    ADD CONSTRAINT backend_pipeline_request_hash_format CHECK (
        request_hash ~ '^[0-9a-f]{64}$'
    );

DROP INDEX IF EXISTS ops.backend_pipeline_idempotency_key;
CREATE UNIQUE INDEX backend_pipeline_idempotency_key
    ON ops.backend_pipeline_request (idempotency_key)
    WHERE idempotency_key IS NOT NULL;

INSERT INTO ops.schema_migration(version)
VALUES ('020_backend_pipeline_idempotency')
ON CONFLICT (version) DO NOTHING;
