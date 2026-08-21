"""
populate_unbalance_prb.py
=========================
ETL script to populate the `unbalance_prb` table from `measKpiBdbh4G`.

Data is processed in **Friday→Thursday** 7-day reporting weeks.
Only complete 7-day periods are inserted.

Usage
-----
  # Incremental: process only new complete weeks not yet in the table
  python scripts/populate_unbalance_prb.py

  # Full recompute: drop existing data and reprocess everything
  python scripts/populate_unbalance_prb.py --all

  # Process a specific date range (will find complete weeks within range)
  python scripts/populate_unbalance_prb.py --start-date 2026-07-01 --end-date 2026-07-31
"""

import os
import sys
import argparse
import logging
from datetime import datetime, timedelta, date

import psycopg2
from dotenv import load_dotenv

# ── Setup ──────────────────────────────────────────────────────────────────────
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR   = os.path.dirname(SCRIPT_DIR)

load_dotenv(os.path.join(ROOT_DIR, '.env'))

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
log = logging.getLogger(__name__)


# ── DB Connection ──────────────────────────────────────────────────────────────
def get_conn():
    return psycopg2.connect(
        dbname   = os.environ.get("POSTGRES_DB_NAME",     "postgres"),
        user     = os.environ.get("POSTGRES_DB_USER",     "postgres"),
        password = os.environ.get("POSTGRES_DB_PASSWORD", "1234"),
        host     = os.environ.get("POSTGRES_DB_HOST",     "localhost"),
        port     = os.environ.get("POSTGRES_DB_PORT",     "5432"),
    )


# ── Custom Friday→Thursday Week ───────────────────────────────────────────────

def custom_week_label(d):
    """Return the custom week label (e.g. '2026-W30') for a given date.

    Custom reporting week: Friday (start) → Thursday (end).
    We shift the date back by 4 days so that Friday maps to Monday,
    then use ISO year/week which starts on Monday.

    Example: 2026-07-30 (Thursday) - 4 = 2026-07-26 (Sunday) → ISO 2026-W30
             2026-07-24 (Friday)   - 4 = 2026-07-20 (Monday) → ISO 2026-W30
             2026-07-31 (Friday)   - 4 = 2026-07-27 (Monday) → ISO 2026-W31
    """
    shifted = d - timedelta(days=4)
    iso_year, iso_week, _ = shifted.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


def friday_of_custom_week(d):
    """Return the Friday that starts the custom week containing date `d`."""
    # weekday(): Monday=0 ... Friday=4 ... Sunday=6
    wd = d.weekday()
    # Days since last Friday: Fri=0, Sat=1, Sun=2, Mon=3, Tue=4, Wed=5, Thu=6
    days_since_friday = (wd - 4) % 7
    return d - timedelta(days=days_since_friday)


def find_complete_weeks(available_dates):
    """Given a sorted list of distinct dates, return list of
    (week_label, friday_start, thursday_end) tuples for complete 7-day periods.
    """
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

    complete = []
    for label, (fri, thu) in sorted(weeks.items()):
        week_dates = [fri + timedelta(days=i) for i in range(7)]
        if all(wd in date_set for wd in week_dates):
            complete.append((label, fri, thu))
        else:
            present = sum(1 for wd in week_dates if wd in date_set)
            log.info("Skipping %s: only %d/7 days present (need complete Fri→Thu)", label, present)

    return complete


# ── Table Creation ─────────────────────────────────────────────────────────────

def create_table_if_not_exists(conn):
    cur = conn.cursor()
    log.info("Ensuring unbalance_prb table exists...")

    sql = '''
    CREATE TABLE IF NOT EXISTS "unbalance_prb" (
        date            DATE NOT NULL,
        subnetwork_name VARCHAR(255),
        me_name         VARCHAR(255),
        cell_id         VARCHAR(50),
        cell_name       VARCHAR(255),
        ul_prb_num      DOUBLE PRECISION,
        ul_prb_denum    DOUBLE PRECISION,
        dl_prb_num      DOUBLE PRECISION,
        dl_prb_denum    DOUBLE PRECISION,
        week            VARCHAR(10) NOT NULL,
        site_id         VARCHAR(50),
        site_id_v2      VARCHAR(50),
        sector          VARCHAR(10),
        band            VARCHAR(20),
        type            VARCHAR(10),
        ul_prb_util     DOUBLE PRECISION,
        dl_prb_util     DOUBLE PRECISION,
        CONSTRAINT unique_unbalance_prb UNIQUE (week, me_name, cell_id, date)
    );
    '''
    cur.execute(sql)
    cur.execute('ALTER TABLE "unbalance_prb" ADD COLUMN IF NOT EXISTS site_id_v2 VARCHAR(50);')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_unbalance_prb_week ON "unbalance_prb"(week);')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_unbalance_prb_site ON "unbalance_prb"(site_id);')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_unbalance_prb_site_v2 ON "unbalance_prb"(site_id_v2);')
    conn.commit()
    cur.close()
    log.info("Table ready.")


# ── Sector / Band / Type derivation (matches existing SQL in kpi_4g_monitoring_routes.py) ──

SECTOR_SQL = '''
    CASE
        WHEN LENGTH("Cell ID"::text) > 2 AND RIGHT("Cell ID"::text, 1) = '5'
            THEN SUBSTRING("Cell ID"::text FROM 2 FOR 1)
        WHEN LENGTH("Cell ID"::text) > 2
            THEN LEFT("Cell ID"::text, 2)
        ELSE LEFT("Cell ID"::text, 1)
    END
'''

BAND_SQL = '''
    CASE RIGHT("Cell ID"::text, 1)
        WHEN '1' THEN 'L1800'
        WHEN '2' THEN 'L900'
        WHEN '3' THEN 'L2100'
        WHEN '4' THEN 'L2300_1'
        WHEN '5' THEN 'L2300_2'
        WHEN '6' THEN 'L2300_3'
        WHEN '7' THEN 'L700'
        ELSE 'Unknown'
    END
'''

# Type (Indoor/Outdoor) — derived using extract_sector_code logic from ta_4g_new_routes.py
# The sector code is extracted from Cell Name, if it starts with 'I' → Indoor, else Outdoor.
# We replicate this in SQL for performance:
TYPE_SQL = '''
    CASE
        WHEN UPPER(
            COALESCE(
                SUBSTRING("Cell Name" FROM '_([A-Za-z]{2})[0-9]+$'),
                SUBSTRING("Cell Name" FROM '[A-Za-z]{3}[0-9]{3}([A-Za-z]{2})')
            )
        ) LIKE 'I%%' THEN 'Indoor'
        ELSE 'Outdoor'
    END
'''


# ── Populate one week ──────────────────────────────────────────────────────────

def populate_week(conn, week_label, friday_start, thursday_end):
    """Delete existing data for this week and re-insert from measKpiBdbh4G."""
    cur = conn.cursor()

    # Delete existing records for this week (idempotent)
    cur.execute('DELETE FROM "unbalance_prb" WHERE week = %s', [week_label])
    deleted = cur.rowcount

    # Custom week SQL expression (must match Python logic)
    # Shift date back 4 days: Friday→Monday alignment, then use ISO year/week
    week_sql = """
        TO_CHAR("Date" - INTERVAL '4 days', 'IYYY') || '-W' ||
        TO_CHAR("Date" - INTERVAL '4 days', 'IW')
    """

    sql = f'''
    INSERT INTO "unbalance_prb" (
        date, subnetwork_name, me_name, cell_id, cell_name,
        ul_prb_num, ul_prb_denum, dl_prb_num, dl_prb_denum,
        week, site_id, site_id_v2, sector, band, type,
        ul_prb_util, dl_prb_util
    )
    SELECT
        sub.date, sub.subnetwork_name, sub.me_name, sub.cell_id, sub.cell_name,
        sub.ul_prb_num, sub.ul_prb_denum, sub.dl_prb_num, sub.dl_prb_denum,
        sub.week, sub.site_id, sub.site_id_v2, sub.sector, sub.band,
        CASE
            WHEN UPPER(
                COALESCE(
                    SUBSTRING(sub.cell_name FROM '_([A-Za-z]{{2}})[0-9]+$'),
                    SUBSTRING(sub.cell_name FROM '[A-Za-z]{{3}}[0-9]{{3}}([A-Za-z]{{2}})')
                )
            ) LIKE 'I%%' THEN 'Indoor'
            ELSE 'Outdoor'
        END AS type,
        sub.ul_prb_util, sub.dl_prb_util
    FROM (
        SELECT
            "Date"::date AS date,
            MAX("Subnetwork Name") AS subnetwork_name,
            "ME Name" AS me_name,
            "Cell ID"::text AS cell_id,
            MAX("Cell Name") AS cell_name,
            SUM("UL PRB Utilization Num") AS ul_prb_num,
            SUM("UL PRB Utilization Denum") AS ul_prb_denum,
            SUM("DL PRB Utilization Num") AS dl_prb_num,
            SUM("DL PRB Utilization Denum") AS dl_prb_denum,
            {week_sql} AS week,
            COALESCE(
                SUBSTRING("ME Name" FROM '([A-Za-z]{{3}}[0-9]{{3}})'),
                SUBSTRING("ME Name", 3, 6)
            ) AS site_id,
            COALESCE(
                SUBSTRING(MAX("Cell Name") FROM '([A-Za-z]{{3}}[0-9]{{3}})'),
                CASE WHEN MAX("Cell Name") LIKE '_%%' THEN SUBSTRING(MAX("Cell Name"), 3, 6) ELSE SUBSTRING(MAX("Cell Name"), 1, 6) END
            ) AS site_id_v2,
            {SECTOR_SQL} AS sector,
            {BAND_SQL} AS band,
            CASE WHEN SUM("UL PRB Utilization Denum") > 0
                 THEN ROUND((SUM("UL PRB Utilization Num") / SUM("UL PRB Utilization Denum") * 100.0)::numeric, 2)
                 ELSE NULL END AS ul_prb_util,
            CASE WHEN SUM("DL PRB Utilization Denum") > 0
                 THEN ROUND((SUM("DL PRB Utilization Num") / SUM("DL PRB Utilization Denum") * 100.0)::numeric, 2)
                 ELSE NULL END AS dl_prb_util
        FROM "measKpiBdbh4G"
        WHERE "Date" >= %s::date AND "Date" <= %s::date
        GROUP BY "Date", "ME Name", "Cell ID"
    ) sub
    '''

    cur.execute(sql, [friday_start.strftime('%Y-%m-%d'), thursday_end.strftime('%Y-%m-%d')])
    inserted = cur.rowcount
    conn.commit()
    cur.close()

    if deleted:
        log.info("  %s: replaced %d → inserted %d rows", week_label, deleted, inserted)
    else:
        log.info("  %s: inserted %d rows", week_label, inserted)


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Populate unbalance_prb table from measKpiBdbh4G (Friday→Thursday weeks)."
    )
    parser.add_argument("--all", action="store_true",
                        help="Drop all existing data and reprocess everything")
    parser.add_argument("--start-date", type=str,
                        help="Start date to consider (YYYY-MM-DD)")
    parser.add_argument("--end-date", type=str,
                        help="End date to consider (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        conn = get_conn()
    except Exception as e:
        log.error("Failed to connect to database: %s", e)
        return

    create_table_if_not_exists(conn)

    cur = conn.cursor()

    # Determine date range from source table
    if args.start_date and args.end_date:
        src_min = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        src_max = datetime.strptime(args.end_date, "%Y-%m-%d").date()
        log.info("Processing date range: %s to %s", src_min, src_max)
    elif args.start_date:
        src_min = datetime.strptime(args.start_date, "%Y-%m-%d").date()
        cur.execute('SELECT MAX("Date"::date) FROM "measKpiBdbh4G"')
        row = cur.fetchone()
        src_max = row[0] if row and row[0] else None
        if not src_max:
            log.warning("No data found in measKpiBdbh4G.")
            conn.close()
            return
        log.info("Processing from %s to %s (latest data)", src_min, src_max)
    else:
        cur.execute('SELECT MIN("Date"::date), MAX("Date"::date) FROM "measKpiBdbh4G"')
        row = cur.fetchone()
        src_min, src_max = (row[0], row[1]) if row else (None, None)
        if not src_min or not src_max:
            log.warning("No data found in measKpiBdbh4G.")
            conn.close()
            return
        log.info("Source data range: %s to %s", src_min, src_max)

    # Get distinct available dates in range
    cur.execute('''
        SELECT DISTINCT "Date"::date AS d
        FROM "measKpiBdbh4G"
        WHERE "Date" >= %s::date AND "Date" <= %s::date
        ORDER BY d
    ''', [src_min.strftime('%Y-%m-%d'), src_max.strftime('%Y-%m-%d')])
    available_dates = [r[0] for r in cur.fetchall()]

    if not available_dates:
        log.warning("No dates found in source data for the given range.")
        conn.close()
        return

    log.info("Found %d distinct dates in source data.", len(available_dates))

    # Find complete Friday→Thursday weeks
    complete_weeks = find_complete_weeks(available_dates)

    if not complete_weeks:
        log.warning("No complete Friday→Thursday weeks found in the data.")
        conn.close()
        return

    log.info("Found %d complete week(s) to process.", len(complete_weeks))

    # In incremental mode, skip weeks already in the table
    if not args.all:
        cur.execute('SELECT DISTINCT week FROM "unbalance_prb" ORDER BY week')
        existing_weeks = {r[0] for r in cur.fetchall()}
        complete_weeks = [(lbl, fri, thu) for lbl, fri, thu in complete_weeks if lbl not in existing_weeks]
        if not complete_weeks:
            log.info("All complete weeks already processed. Nothing to do.")
            conn.close()
            return
        log.info("After skipping existing: %d new week(s) to process.", len(complete_weeks))

    cur.close()

    # Process each week
    for week_label, fri, thu in complete_weeks:
        populate_week(conn, week_label, fri, thu)

    conn.close()
    log.info("Done! Processed %d week(s) into unbalance_prb.", len(complete_weeks))

    # Also populate unbalance_prb_weekly
    try:
        log.info("Now populating unbalance_prb_weekly table...")
        import populate_unbalance_prb_weekly
        populate_unbalance_prb_weekly.main()
    except Exception as e:
        log.warning("Could not populate unbalance_prb_weekly: %s", e)


if __name__ == "__main__":
    main()
