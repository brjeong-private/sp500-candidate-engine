ALTER TABLE fundamental.sec_filing
    DROP CONSTRAINT IF EXISTS sec_filing_accession_no_key;

CREATE UNIQUE INDEX IF NOT EXISTS ux_sec_filing_issuer_accession
    ON fundamental.sec_filing(issuer_id, accession_no);

INSERT INTO ops.schema_migration(version)
VALUES ('009_sec_filing_identity')
ON CONFLICT (version) DO NOTHING;
