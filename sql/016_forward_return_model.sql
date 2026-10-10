ALTER TABLE analytics.model_version
    ADD COLUMN IF NOT EXISTS label_semantics text NOT NULL DEFAULT 'LEGACY_EXCESS_RETURN';

ALTER TABLE analytics.scoring_run
    ADD COLUMN IF NOT EXISTS score_semantics text NOT NULL DEFAULT 'LEGACY_SCORE';

ALTER TABLE analytics.daily_score
    ADD COLUMN IF NOT EXISTS predicted_return real;

ALTER TABLE selection.candidate
    ADD COLUMN IF NOT EXISTS predicted_return real;

INSERT INTO ops.schema_migration(version)
VALUES ('016_forward_return_model')
ON CONFLICT (version) DO NOTHING;
