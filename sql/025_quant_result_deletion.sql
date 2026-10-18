CREATE TABLE IF NOT EXISTS selection.quant_result_deletion (
    selection_run_id uuid PRIMARY KEY
        REFERENCES selection.selection_run(selection_run_id),
    deleted_at timestamptz NOT NULL DEFAULT now(),
    reason text NOT NULL CHECK (length(trim(reason)) > 0)
);

INSERT INTO ops.schema_migration(version)
VALUES ('025_quant_result_deletion')
ON CONFLICT (version) DO NOTHING;
