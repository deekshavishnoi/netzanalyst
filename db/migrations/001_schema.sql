-- netzanalyst schema
-- Source: SMARD (Bundesnetzagentur), CC BY 4.0. See data/README.md.
--
-- Time handling
--   ts  is timestamptz, stored in UTC (SMARD publishes epoch milliseconds).
--   German electricity questions are almost always asked in German local time
--   ("July 2025", "last Tuesday evening"), so every view also exposes
--   ts_berlin = ts AT TIME ZONE 'Europe/Berlin'. Prefer the views for
--   calendar-based filtering; Europe/Berlin observes DST.
--
-- Units
--   Generation and consumption are MWh per interval. At hourly resolution the
--   numeric value equals the average MW over that hour.
--   Prices are EUR per MWh (day-ahead wholesale; may be negative).

BEGIN;

CREATE TABLE IF NOT EXISTS generation_source (
    source            text PRIMARY KEY,
    label             text        NOT NULL,
    category          text        NOT NULL
                      CHECK (category IN ('renewable', 'conventional', 'storage')),
    smard_filter_id   integer     NOT NULL UNIQUE
);

COMMENT ON TABLE generation_source IS
    'Dimension table: one row per electricity generation source. Join to generation.source.';
COMMENT ON COLUMN generation_source.category IS
    'renewable | conventional | storage. Pumped storage is "storage", not renewable: '
    'Germany''s official renewable-share figures exclude it.';

CREATE TABLE IF NOT EXISTS generation (
    ts      timestamptz       NOT NULL,
    source  text              NOT NULL REFERENCES generation_source(source),
    mwh     double precision,
    PRIMARY KEY (ts, source)
);

COMMENT ON TABLE generation IS
    'Actual electricity generation in Germany, one row per hour per source. mwh may be NULL when SMARD has not published a value.';

CREATE TABLE IF NOT EXISTS consumption (
    ts      timestamptz       NOT NULL,
    metric  text              NOT NULL
            CHECK (metric IN ('total_load', 'residual_load', 'pumped_storage_consumption')),
    mwh     double precision,
    PRIMARY KEY (ts, metric)
);

COMMENT ON TABLE consumption IS
    'Actual electricity consumption in Germany, one row per hour per metric. '
    'total_load = grid load (Netzlast); residual_load = load minus wind and solar.';

CREATE TABLE IF NOT EXISTS price (
    ts            timestamptz   NOT NULL,
    bidding_zone  text          NOT NULL,
    eur_per_mwh   double precision,
    PRIMARY KEY (ts, bidding_zone)
);

COMMENT ON TABLE price IS
    'Day-ahead wholesale electricity price, one row per hour per bidding zone. '
    'Germany/Luxembourg is bidding_zone = ''DE-LU''. Prices can be negative.';

-- Provenance: which SMARD week-chunks have already been loaded.
CREATE TABLE IF NOT EXISTS ingest_log (
    smard_filter_id  integer      NOT NULL,
    region           text         NOT NULL,
    resolution       text         NOT NULL,
    chunk_start      timestamptz  NOT NULL,
    row_count        integer      NOT NULL,
    fetched_at       timestamptz  NOT NULL DEFAULT now(),
    PRIMARY KEY (smard_filter_id, region, resolution, chunk_start)
);

CREATE INDEX IF NOT EXISTS generation_ts_idx   ON generation (ts);
CREATE INDEX IF NOT EXISTS generation_src_idx  ON generation (source, ts);
CREATE INDEX IF NOT EXISTS consumption_ts_idx  ON consumption (ts);
CREATE INDEX IF NOT EXISTS price_ts_idx        ON price (ts);

INSERT INTO generation_source (source, label, category, smard_filter_id) VALUES
    ('lignite',            'Lignite (brown coal)',  'conventional', 1223),
    ('nuclear',            'Nuclear',               'conventional', 1224),
    ('wind_offshore',      'Wind offshore',         'renewable',    1225),
    ('hydro',              'Hydropower',            'renewable',    1226),
    ('other_conventional', 'Other conventional',    'conventional', 1227),
    ('other_renewable',    'Other renewable',       'renewable',    1228),
    ('biomass',            'Biomass',               'renewable',    4066),
    ('wind_onshore',       'Wind onshore',          'renewable',    4067),
    ('solar',              'Solar (photovoltaic)',  'renewable',    4068),
    ('hard_coal',          'Hard coal',             'conventional', 4069),
    ('pumped_storage',     'Pumped storage',        'storage',      4070),
    ('natural_gas',        'Natural gas',           'conventional', 4071)
ON CONFLICT (source) DO NOTHING;

-- ---------------------------------------------------------------------------
-- Views. Agents should prefer these: they carry Berlin local time and the
-- renewable-share arithmetic that is easy to get subtly wrong.
-- ---------------------------------------------------------------------------

CREATE OR REPLACE VIEW v_generation AS
SELECT g.ts,
       (g.ts AT TIME ZONE 'Europe/Berlin')       AS ts_berlin,
       g.source,
       s.label,
       s.category,
       g.mwh
FROM generation g
JOIN generation_source s USING (source);

COMMENT ON VIEW v_generation IS
    'Hourly generation with Berlin local time and source category. Start here for most questions.';

CREATE OR REPLACE VIEW v_generation_daily AS
SELECT date_trunc('day', g.ts AT TIME ZONE 'Europe/Berlin')::date AS day_berlin,
       g.source,
       s.category,
       sum(g.mwh) AS mwh
FROM generation g
JOIN generation_source s USING (source)
GROUP BY 1, 2, 3;

CREATE OR REPLACE VIEW v_generation_monthly AS
SELECT date_trunc('month', g.ts AT TIME ZONE 'Europe/Berlin')::date AS month_berlin,
       g.source,
       s.category,
       sum(g.mwh) AS mwh
FROM generation g
JOIN generation_source s USING (source)
GROUP BY 1, 2, 3;

-- Share of total generation, by source, per month.
-- Denominator is total generation EXCLUDING pumped storage, which matches how
-- SMARD and Fraunhofer ISE report the renewable share.
CREATE OR REPLACE VIEW v_generation_share_monthly AS
WITH totals AS (
    SELECT month_berlin, sum(mwh) AS total_mwh
    FROM v_generation_monthly
    WHERE category <> 'storage'
    GROUP BY 1
)
SELECT m.month_berlin,
       m.source,
       m.category,
       m.mwh,
       t.total_mwh,
       CASE WHEN t.total_mwh > 0 THEN 100.0 * m.mwh / t.total_mwh END AS pct_of_generation
FROM v_generation_monthly m
JOIN totals t USING (month_berlin)
WHERE m.category <> 'storage';

COMMENT ON VIEW v_generation_share_monthly IS
    'Monthly share of total generation per source, in percent. Denominator excludes '
    'pumped storage, matching how SMARD and Fraunhofer ISE report renewable share.';

CREATE OR REPLACE VIEW v_renewable_share_monthly AS
SELECT month_berlin,
       sum(mwh) FILTER (WHERE category = 'renewable')              AS renewable_mwh,
       sum(mwh)                                                    AS total_mwh,
       100.0 * sum(mwh) FILTER (WHERE category = 'renewable')
             / NULLIF(sum(mwh), 0)                                 AS renewable_pct
FROM v_generation_monthly
WHERE category <> 'storage'
GROUP BY 1;

CREATE OR REPLACE VIEW v_price AS
SELECT ts,
       (ts AT TIME ZONE 'Europe/Berlin') AS ts_berlin,
       bidding_zone,
       eur_per_mwh
FROM price;

CREATE OR REPLACE VIEW v_consumption AS
SELECT ts,
       (ts AT TIME ZONE 'Europe/Berlin') AS ts_berlin,
       metric,
       mwh
FROM consumption;

-- What the data actually covers. The agents should check this before
-- answering questions about periods that may not be loaded.
CREATE OR REPLACE VIEW v_data_coverage AS
SELECT 'generation'  AS table_name, min(ts) AS first_ts, max(ts) AS last_ts, count(*) AS row_count FROM generation
UNION ALL
SELECT 'consumption', min(ts), max(ts), count(*) FROM consumption
UNION ALL
SELECT 'price',       min(ts), max(ts), count(*) FROM price;

COMMENT ON VIEW v_data_coverage IS
    'Date range and row count actually present in each table. Check this before '
    'answering questions about a period, so the answer is not silently based on partial data.';

COMMIT;
