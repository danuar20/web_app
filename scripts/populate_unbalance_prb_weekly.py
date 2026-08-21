"""
populate_unbalance_prb_weekly.py
================================
Automated weekly processing script to generate the `unbalance_prb_weekly` table
from `unbalance_prb` for complete Friday-to-Thursday reporting weeks.

Designed for automated execution via Linux cronjob or manual trigger.

Usage
-----
  # Incremental mode (suitable for cron): process complete weeks not yet in unbalance_prb_weekly
  python scripts/populate_unbalance_prb_weekly.py

  # Full recompute mode: drop and re-aggregate all complete weeks
  python scripts/populate_unbalance_prb_weekly.py --all

  # Date range filter (finds complete weeks within window):
  python scripts/populate_unbalance_prb_weekly.py --start-date 2026-01-01 --end-date 2026-08-01

Cronjob Example (Linux)
-----------------------
  # Run daily at 03:30 AM
  30 3 * * * cd /path/to/web_app && ./venv/bin/python scripts/populate_unbalance_prb_weekly.py >> logs/unbalance_prb_weekly.log 2>&1
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, date

import psycopg2
from dotenv import load_dotenv

# ── Project Path & Env Setup (Cron-safe absolute paths) ────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)
load_dotenv(os.path.join(ROOT_DIR, '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


# ── DB Connection (reuses db_webapp configuration) ────────────────────────────
def get_conn():
    return psycopg2.connect(
        dbname   = os.environ.get("POSTGRES_DB_NAME",     "postgres"),
        user     = os.environ.get("POSTGRES_DB_USER",     "postgres"),
        password = os.environ.get("POSTGRES_DB_PASSWORD", "1234"),
        host     = os.environ.get("POSTGRES_DB_HOST",     "localhost"),
        port     = os.environ.get("POSTGRES_DB_PORT",     "5432"),
    )


# ── Friday-to-Thursday Business Week Logic ────────────────────────────────────

def custom_week_label(d):
    """Return custom week label (e.g. '2026-W30') for date `d`.
    Business week runs Friday → Thursday.
    """
    shifted = d - timedelta(days=4)
    iso_year, iso_week, _ = shifted.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def friday_of_custom_week(d):
    """Return Friday start date for the custom week containing `d`."""
    wd = d.weekday()  # Mon=0 ... Fri=4 ... Sun=6
    days_since_friday = (wd - 4) % 7
    return d - timedelta(days=days_since_friday)


def check_complete_weeks(conn, min_date=None, max_date=None):
    """Query `unbalance_prb` to find complete 7-day Friday-to-Thursday weeks."""
    cur = conn.cursor()

    where_clause = ""
    params = []
    if min_date and max_date:
        where_clause = "WHERE date >= %s::date AND date <= %s::date"
        params = [min_date.strftime('%Y-%m-%d'), max_date.strftime('%Y-%m-%d')]

    cur.execute(f'SELECT DISTINCT date FROM "unbalance_prb" {where_clause} ORDER BY date', params)
    available_dates = [r[0] for r in cur.fetchall()]
    cur.close()

    if not available_dates:
        return []

    date_set = set(available_dates)
    weeks = {}

    for d in available_dates:
        label = custom_week_label(d)
        if label not in weeks:
            fri = friday_of_custom_week(d)
            thu = fri + timedelta(days=6)
            weeks[label] = (fri, thu)

    complete_weeks = []
    for label, (fri, thu) in sorted(weeks.items()):
        week_dates = [fri + timedelta(days=i) for i in range(7)]
        present_count = sum(1 for wd in week_dates if wd in date_set)
        if present_count == 7:
            complete_weeks.append((label, fri, thu, 7))
        else:
            log.info("Week: %s", label)
            log.info("Period: %s → %s", fri.strftime('%Y-%m-%d'), thu.strftime('%Y-%m-%d'))
            log.info("Available days: %d/7", present_count)
            log.info("Status: INCOMPLETE — Skipping processing.\n")

    return complete_weeks


# ── Table Creation ─────────────────────────────────────────────────────────────

def create_table_if_not_exists(conn):
    cur = conn.cursor()
    log.info("Ensuring unbalance_prb_weekly table exists...")

    sql = '''
    CREATE TABLE IF NOT EXISTS "unbalance_prb_weekly" (
        "week"            VARCHAR(10) NOT NULL,
        "site_id"         VARCHAR(50) NOT NULL,
        "site_id_v2"      VARCHAR(50),
        "sector"          VARCHAR(10) NOT NULL,
        "type"            VARCHAR(10) NOT NULL,
        "num_band"        INTEGER,
        "dl_L900"         DOUBLE PRECISION,
        "dl_L1800"        DOUBLE PRECISION,
        "dl_L2100"        DOUBLE PRECISION,
        "dl_L2300_1"      DOUBLE PRECISION,
        "dl_L2300_2"      DOUBLE PRECISION,
        "dl_L2300_3"      DOUBLE PRECISION,
        "dl_L700"         DOUBLE PRECISION,
        "avg_dl_prb"      DOUBLE PRECISION,
        "max_dl_prb"      DOUBLE PRECISION,
        "max_dl_band"     VARCHAR(20),
        "min_dl_band"     VARCHAR(20),
        "ul_L900"         DOUBLE PRECISION,
        "ul_L1800"        DOUBLE PRECISION,
        "ul_L2100"        DOUBLE PRECISION,
        "ul_L2300_1"      DOUBLE PRECISION,
        "ul_L2300_2"      DOUBLE PRECISION,
        "ul_L2300_3"      DOUBLE PRECISION,
        "ul_L700"         DOUBLE PRECISION,
        "avg_ul_prb"      DOUBLE PRECISION,
        "max_ul_prb"      DOUBLE PRECISION,
        "max_ul_band"     VARCHAR(20),
        "min_ul_band"     VARCHAR(20),
        CONSTRAINT unique_unbalance_prb_weekly UNIQUE ("week", "site_id", "site_id_v2", "sector", "type")
    );
    '''
    cur.execute(sql)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_unbalance_prb_weekly_week ON "unbalance_prb_weekly"("week");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_unbalance_prb_weekly_site ON "unbalance_prb_weekly"("site_id");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_unbalance_prb_weekly_site_v2 ON "unbalance_prb_weekly"("site_id_v2");')
    conn.commit()
    cur.close()
    log.info("Table ready.")


# ── Populate One Week ──────────────────────────────────────────────────────────

def populate_week(conn, week_label, friday_start, thursday_end):
    """Aggregate unbalance_prb by week + site_id + site_id_v2 + sector + type."""
    cur = conn.cursor()

    cur.execute('DELETE FROM "unbalance_prb_weekly" WHERE "week" = %s', [week_label])
    deleted = cur.rowcount

    sql = '''
    INSERT INTO "unbalance_prb_weekly" (
        "week", "site_id", "site_id_v2", "sector", "type", "num_band",
        "dl_L900", "dl_L1800", "dl_L2100", "dl_L2300_1", "dl_L2300_2", "dl_L2300_3", "dl_L700",
        "avg_dl_prb", "max_dl_prb", "max_dl_band", "min_dl_band",
        "ul_L900", "ul_L1800", "ul_L2100", "ul_L2300_1", "ul_L2300_2", "ul_L2300_3", "ul_L700",
        "avg_ul_prb", "max_ul_prb", "max_ul_band", "min_ul_band"
    )
    WITH band_agg AS (
        SELECT
            week, site_id, site_id_v2, sector, type, band,
            SUM(dl_prb_num) AS dl_num, SUM(dl_prb_denum) AS dl_den,
            SUM(ul_prb_num) AS ul_num, SUM(ul_prb_denum) AS ul_den,
            CASE WHEN SUM(dl_prb_denum) > 0 THEN ROUND((SUM(dl_prb_num) / SUM(dl_prb_denum) * 100.0)::numeric, 2) ELSE NULL END AS dl_util,
            CASE WHEN SUM(ul_prb_denum) > 0 THEN ROUND((SUM(ul_prb_num) / SUM(ul_prb_denum) * 100.0)::numeric, 2) ELSE NULL END AS ul_util
        FROM "unbalance_prb"
        WHERE week = %s
        GROUP BY week, site_id, site_id_v2, sector, type, band
    )
    SELECT
        week, site_id, site_id_v2, sector, type,
        COUNT(DISTINCT CASE WHEN band IS NOT NULL AND band != 'Unknown' THEN band END) AS num_band,

        -- DL PRB per Band (CamelCase Quoted Column Names)
        MAX(CASE WHEN band = 'L900' THEN dl_util END) AS "dl_L900",
        MAX(CASE WHEN band = 'L1800' THEN dl_util END) AS "dl_L1800",
        MAX(CASE WHEN band = 'L2100' THEN dl_util END) AS "dl_L2100",
        MAX(CASE WHEN band IN ('L2300', 'L2300_1') THEN dl_util END) AS "dl_L2300_1",
        MAX(CASE WHEN band = 'L2300_2' THEN dl_util END) AS "dl_L2300_2",
        MAX(CASE WHEN band = 'L2300_3' THEN dl_util END) AS "dl_L2300_3",
        MAX(CASE WHEN band = 'L700' THEN dl_util END) AS "dl_L700",

        -- DL PRB Summary
        CASE WHEN SUM(dl_den) > 0 THEN ROUND((SUM(dl_num) / SUM(dl_den) * 100.0)::numeric, 2) ELSE NULL END AS avg_dl_prb,
        MAX(dl_util) AS max_dl_prb,
        (ARRAY_AGG(band ORDER BY dl_util DESC NULLS LAST))[1] AS max_dl_band,
        (ARRAY_AGG(band ORDER BY dl_util ASC NULLS LAST))[1] AS min_dl_band,

        -- UL PRB per Band (CamelCase Quoted Column Names)
        MAX(CASE WHEN band = 'L900' THEN ul_util END) AS "ul_L900",
        MAX(CASE WHEN band = 'L1800' THEN ul_util END) AS "ul_L1800",
        MAX(CASE WHEN band = 'L2100' THEN ul_util END) AS "ul_L2100",
        MAX(CASE WHEN band IN ('L2300', 'L2300_1') THEN ul_util END) AS "ul_L2300_1",
        MAX(CASE WHEN band = 'L2300_2' THEN ul_util END) AS "ul_L2300_2",
        MAX(CASE WHEN band = 'L2300_3' THEN ul_util END) AS "ul_L2300_3",
        MAX(CASE WHEN band = 'L700' THEN ul_util END) AS "ul_L700",

        -- UL PRB Summary
        CASE WHEN SUM(ul_den) > 0 THEN ROUND((SUM(ul_num) / SUM(ul_den) * 100.0)::numeric, 2) ELSE NULL END AS avg_ul_prb,
        MAX(ul_util) AS max_ul_prb,
        (ARRAY_AGG(band ORDER BY ul_util DESC NULLS LAST))[1] AS max_ul_band,
        (ARRAY_AGG(band ORDER BY ul_util ASC NULLS LAST))[1] AS min_ul_band
    FROM band_agg
    GROUP BY week, site_id, site_id_v2, sector, type
    '''

    cur.execute(sql, [week_label])
    inserted = cur.rowcount
    conn.commit()
    cur.close()

    log.info("Week: %s", week_label)
    log.info("Period: %s → %s", friday_start.strftime('%Y-%m-%d'), thursday_end.strftime('%Y-%m-%d'))
    log.info("Available days: 7/7")
    log.info("Status: COMPLETE")
    log.info("Rows inserted/updated: %d\n", inserted)


# ── Main Execution ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Automated ETL script to populate unbalance_prb_weekly from unbalance_prb."
    )
    parser.add_argument("--all", action="store_true",
                        help="Re-aggregate all complete weeks")
    parser.add_argument("--start-date", type=str,
                        help="Start date filter (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str,
                        help="End date filter (YYYY-MM-DD)")
    args = parser.parse_args()

    log.info("==================================================")
    log.info("Unbalance PRB Weekly Processing")
    log.info("==================================================")

    try:
        conn = get_conn()
        log.info("Database connection: OK\n")
    except Exception as e:
        log.error("Database connection: FAILED (%s)", e)
        sys.exit(1)

    log.info("Source table: unbalance_prb")
    log.info("Target table: unbalance_prb_weekly\n")

    create_table_if_not_exists(conn)

    min_d = datetime.strptime(args.start_date, "%Y-%m-%d").date() if args.start_date else None
    max_d = datetime.strptime(args.end_date, "%Y-%m-%d").date() if args.end_date else None

    log.info("Checking complete weeks...")
    complete_weeks = check_complete_weeks(conn, min_d, max_d)

    if not complete_weeks:
        log.info("No complete Friday-to-Thursday weeks to process.")
        conn.close()
        return

    if not args.all:
        cur = conn.cursor()
        cur.execute('SELECT DISTINCT week FROM "unbalance_prb_weekly"')
        existing = {r[0] for r in cur.fetchall()}
        cur.close()

        complete_weeks = [w for w in complete_weeks if w[0] not in existing]
        if not complete_weeks:
            log.info("All complete weeks already processed in unbalance_prb_weekly. Nothing to do.")
            conn.close()
            return

    log.info("Processing %d complete week(s)...\n", len(complete_weeks))

    for label, fri, thu, _ in complete_weeks:
        populate_week(conn, label, fri, thu)

    conn.close()
    log.info("Processing completed successfully.")


if __name__ == "__main__":
    main()
