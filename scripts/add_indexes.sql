-- ============================================================================
-- NetKPI Monitor — Performance Indexes
-- Run this on your PostgreSQL database to improve query performance.
-- All indexes use IF NOT EXISTS so it's safe to re-run.
-- Uses CONCURRENTLY to avoid locking tables during creation.
-- ============================================================================

-- ── 4G KPI Tables ──────────────────────────────────────────────────────────────

-- Most 4G queries filter by date + siteid (hourly, dashboard, compare views)
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_4g_kpi_zte_date_siteid
    ON "4g_kpi_zte" (date, siteid);

-- Dashboard and monitoring queries filter by datehour
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_4g_kpi_zte_datehour
    ON "4g_kpi_zte" (datehour);

-- Sector-level queries filter by date + cell
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_4g_kpi_zte_date_cell
    ON "4g_kpi_zte" (date, cell);

-- Daily aggregate table used by monitoring views
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_4g_kpi_zte_daily_kpidate
    ON "4g_kpi_zte_daily" (kpi_date);


-- ── 5G KPI Tables ──────────────────────────────────────────────────────────────

-- 5G queries filter by datehour + siteid
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_5g_kpi_zte_datehour_siteid
    ON "5g_kpi_zte" (datehour, siteid);

-- 5G queries also filter by datehour + cellid for sector views
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_5g_kpi_zte_datehour_cellid
    ON "5g_kpi_zte" (datehour, cellid);


-- ── 2G KPI Tables ──────────────────────────────────────────────────────────────

-- 2G queries filter by datehour + siteid
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_2g_kpi_zte_datehour_siteid
    ON "2g_kpi_zte" (datehour, siteid);

-- 2G sector queries filter by datehour + bts
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_2g_kpi_zte_datehour_bts
    ON "2g_kpi_zte" (datehour, bts);


-- ── Traffic Payload Table ──────────────────────────────────────────────────────

-- Productivity page queries by Date + Year_by_Date
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tp_date_year
    ON traffic_payload ("Date", "Year by Date");

-- City/Site level queries by Date + NSA
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tp_date_nsa
    ON traffic_payload ("Date", "NSA");

-- City level queries by Date + KABUPATEN
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tp_date_kabupaten
    ON traffic_payload ("Date", "KABUPATEN");

-- Week-over-week comparison queries by Y_W
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tp_yw
    ON traffic_payload ("Y_W");

-- Site level queries by Date + Site_ID
CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_tp_date_siteid
    ON traffic_payload ("Date", "Site ID");


-- ── Packet Loss Tables ─────────────────────────────────────────────────────────

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_2g_pl_date
    ON "2G_pl_hy" ("Date");

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_4g_pl_date
    ON "4G_pl_hy" (date);


-- ── TA 4G Table ────────────────────────────────────────────────────────────────

CREATE INDEX CONCURRENTLY IF NOT EXISTS idx_ta4g_date
    ON "measTA4G" ("Date");


-- ── Verify indexes were created ────────────────────────────────────────────────
SELECT schemaname, tablename, indexname
FROM pg_indexes
WHERE tablename IN (
    '4g_kpi_zte', '5g_kpi_zte', '2g_kpi_zte',
    'traffic_payload', '4g_kpi_zte_daily',
    '2G_pl_hy', '4G_pl_hy', 'measTA4G'
)
ORDER BY tablename, indexname;
