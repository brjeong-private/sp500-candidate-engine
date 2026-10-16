CREATE TABLE IF NOT EXISTS analytics.weekly_training_run (
    weekly_run_id uuid PRIMARY KEY,
    iso_week text NOT NULL CHECK (iso_week ~ '^[0-9]{4}-W[0-9]{2}$'),
    anchor_session date NOT NULL,
    model_purpose text NOT NULL CHECK (model_purpose IN ('SHORT_5D', 'MEDIUM_20D')),
    policy_version text NOT NULL,
    input_manifest_id uuid NOT NULL
        REFERENCES ops.input_manifest(input_manifest_id),
    training_cutoff timestamptz NOT NULL,
    label_maturity_cutoff date NOT NULL,
    container_job_execution_name text,
    status text NOT NULL CHECK (
        status IN (
            'PENDING', 'RUNNING', 'EVALUATED', 'PROMOTED',
            'REJECTED', 'ROLLED_BACK', 'FAILED'
        )
    ),
    export_run_id uuid REFERENCES analytics.qlib_export_run(export_run_id),
    challenger_model_version_id uuid
        REFERENCES analytics.model_version(model_version_id),
    champion_model_version_id uuid
        REFERENCES analytics.model_version(model_version_id),
    error_code text,
    error_message text,
    started_at timestamptz,
    finished_at timestamptz,
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (iso_week, model_purpose, policy_version, input_manifest_id),
    UNIQUE (weekly_run_id, model_purpose),
    CHECK ((error_code IS NULL) = (error_message IS NULL)),
    CHECK (error_message IS NULL OR length(error_message) <= 500)
);

CREATE TABLE IF NOT EXISTS analytics.model_promotion_decision (
    promotion_decision_id uuid PRIMARY KEY,
    weekly_run_id uuid NOT NULL UNIQUE
        REFERENCES analytics.weekly_training_run(weekly_run_id),
    incumbent_model_version_id uuid
        REFERENCES analytics.model_version(model_version_id),
    challenger_model_version_id uuid NOT NULL
        REFERENCES analytics.model_version(model_version_id),
    policy_version text NOT NULL,
    decision text NOT NULL CHECK (decision IN ('PROMOTE', 'REJECT')),
    gate_results jsonb NOT NULL,
    decided_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'model_version_id_purpose_key'
           AND conrelid = 'analytics.model_version'::regclass
    ) THEN
        ALTER TABLE analytics.model_version
            ADD CONSTRAINT model_version_id_purpose_key
            UNIQUE (model_version_id, model_purpose);
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS analytics.active_model_assignment (
    model_purpose text PRIMARY KEY CHECK (model_purpose IN ('SHORT_5D', 'MEDIUM_20D')),
    model_version_id uuid NOT NULL
        REFERENCES analytics.model_version(model_version_id),
    artifact_uri text NOT NULL,
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    blob_etag text,
    blob_version_id text,
    generation bigint NOT NULL CHECK (generation > 0),
    weekly_run_id uuid NOT NULL
        REFERENCES analytics.weekly_training_run(weekly_run_id),
    activated_at timestamptz NOT NULL DEFAULT now(),
    FOREIGN KEY (model_version_id, model_purpose)
        REFERENCES analytics.model_version(model_version_id, model_purpose),
    FOREIGN KEY (weekly_run_id, model_purpose)
        REFERENCES analytics.weekly_training_run(weekly_run_id, model_purpose),
    CHECK (artifact_uri <> ''),
    CHECK (blob_etag IS NOT NULL OR blob_version_id IS NOT NULL)
);

CREATE TABLE IF NOT EXISTS analytics.active_model_assignment_history (
    assignment_history_id uuid PRIMARY KEY,
    model_purpose text NOT NULL CHECK (model_purpose IN ('SHORT_5D', 'MEDIUM_20D')),
    model_version_id uuid NOT NULL
        REFERENCES analytics.model_version(model_version_id),
    artifact_uri text NOT NULL,
    artifact_hash text NOT NULL CHECK (artifact_hash ~ '^[0-9a-f]{64}$'),
    blob_etag text,
    blob_version_id text,
    generation bigint NOT NULL CHECK (generation > 0),
    weekly_run_id uuid NOT NULL
        REFERENCES analytics.weekly_training_run(weekly_run_id),
    action text NOT NULL CHECK (action IN ('ACTIVATE', 'ROLLBACK')),
    replaced_model_version_id uuid
        REFERENCES analytics.model_version(model_version_id),
    recorded_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE (model_purpose, generation),
    FOREIGN KEY (model_version_id, model_purpose)
        REFERENCES analytics.model_version(model_version_id, model_purpose),
    FOREIGN KEY (weekly_run_id, model_purpose)
        REFERENCES analytics.weekly_training_run(weekly_run_id, model_purpose),
    CHECK (artifact_uri <> ''),
    CHECK (blob_etag IS NOT NULL OR blob_version_id IS NOT NULL)
);

CREATE UNIQUE INDEX IF NOT EXISTS model_version_one_champion_per_purpose
    ON analytics.model_version(model_purpose)
    WHERE promotion_status = 'CHAMPION';

CREATE INDEX IF NOT EXISTS weekly_training_run_status
    ON analytics.weekly_training_run(status, created_at);

INSERT INTO ops.schema_migration(version)
VALUES ('021_weekly_retraining')
ON CONFLICT (version) DO NOTHING;