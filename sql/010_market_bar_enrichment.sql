ALTER TABLE market.daily_bar
    ADD COLUMN IF NOT EXISTS vwap numeric(20, 8),
    ADD COLUMN IF NOT EXISTS price_adjustment_status text NOT NULL DEFAULT 'UNKNOWN',
    ADD COLUMN IF NOT EXISTS volume_adjustment_status text NOT NULL DEFAULT 'UNKNOWN';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'daily_bar_price_adjustment_status_check'
           AND conrelid = 'market.daily_bar'::regclass
    ) THEN
        ALTER TABLE market.daily_bar
            ADD CONSTRAINT daily_bar_price_adjustment_status_check
            CHECK (
                price_adjustment_status IN (
                    'UNKNOWN',
                    'UNADJUSTED',
                    'UNADJUSTED_WITH_ADJUSTED_CLOSE',
                    'SPLIT_ADJUSTED',
                    'TOTAL_RETURN_ADJUSTED'
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'daily_bar_volume_adjustment_status_check'
           AND conrelid = 'market.daily_bar'::regclass
    ) THEN
        ALTER TABLE market.daily_bar
            ADD CONSTRAINT daily_bar_volume_adjustment_status_check
            CHECK (
                volume_adjustment_status IN ('UNKNOWN', 'UNADJUSTED', 'SPLIT_ADJUSTED')
            );
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS market.benchmark_daily_bar (
    benchmark_code text NOT NULL,
    session_date date NOT NULL,
    source_id bigint NOT NULL REFERENCES ops.data_source(source_id),
    revision_no integer NOT NULL CHECK (revision_no > 0),
    open numeric(20, 8) NOT NULL CHECK (open > 0),
    high numeric(20, 8) NOT NULL CHECK (high > 0),
    low numeric(20, 8) NOT NULL CHECK (low > 0),
    close numeric(20, 8) NOT NULL CHECK (close > 0),
    volume bigint NOT NULL CHECK (volume >= 0),
    vwap numeric(20, 8),
    return_basis text NOT NULL,
    price_adjustment_status text NOT NULL,
    volume_adjustment_status text NOT NULL,
    source_timestamp timestamptz NOT NULL,
    source_available_at timestamptz NOT NULL,
    observed_at timestamptz NOT NULL,
    source_snapshot_id uuid NOT NULL REFERENCES ops.source_snapshot(source_snapshot_id),
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (benchmark_code, session_date, source_id, revision_no),
    CHECK (low <= high),
    CHECK (open BETWEEN low AND high),
    CHECK (close BETWEEN low AND high),
    CHECK (return_basis IN ('PRICE_RETURN', 'TOTAL_RETURN')),
    CHECK (
        price_adjustment_status IN (
            'UNADJUSTED',
            'UNADJUSTED_WITH_ADJUSTED_CLOSE',
            'SPLIT_ADJUSTED',
            'TOTAL_RETURN_ADJUSTED'
        )
    ),
    CHECK (volume_adjustment_status IN ('UNADJUSTED', 'SPLIT_ADJUSTED'))
);

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'benchmark_price_adjustment_status_check'
           AND conrelid = 'market.benchmark_daily_bar'::regclass
    ) THEN
        ALTER TABLE market.benchmark_daily_bar
            ADD CONSTRAINT benchmark_price_adjustment_status_check
            CHECK (
                price_adjustment_status IN (
                    'UNADJUSTED',
                    'UNADJUSTED_WITH_ADJUSTED_CLOSE',
                    'SPLIT_ADJUSTED',
                    'TOTAL_RETURN_ADJUSTED'
                )
            );
    END IF;
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint
         WHERE conname = 'benchmark_volume_adjustment_status_check'
           AND conrelid = 'market.benchmark_daily_bar'::regclass
    ) THEN
        ALTER TABLE market.benchmark_daily_bar
            ADD CONSTRAINT benchmark_volume_adjustment_status_check
            CHECK (volume_adjustment_status IN ('UNADJUSTED', 'SPLIT_ADJUSTED'));
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS benchmark_daily_bar_code_date
    ON market.benchmark_daily_bar(benchmark_code, session_date DESC);

INSERT INTO ops.schema_migration(version)
VALUES ('010_market_bar_enrichment')
ON CONFLICT (version) DO NOTHING;
