"""
populate_pl_daily.py
====================
ETL script to populate pre-aggregated daily Packet Loss tables:
    - 4G_pl_hy_daily   (from 4G_pl_hy)
    - 2G_pl_hy_daily   (from 2G_pl_hy)

Usage
-----
  # Incremental: process only missing/recent dates (default, suitable for cron)
  python populate_pl_daily.py

  # Backfill from a specific start date (first-time setup or manual recompute)
  python populate_pl_daily.py --start-date 2026-01-01

  # Recompute a specific date range (manual trigger after data correction)
  python populate_pl_daily.py --start-date 2026-06-01 --end-date 2026-06-30 --force

  # Process 4G only or 2G only
  python populate_pl_daily.py --tech 4G
  python populate_pl_daily.py --tech 2G

Scheduling (Windows Task Scheduler / cron)
------------------------------------------
  Recommended: run daily at 03:00 AM (after data lands)
  Cron example:
    0 3 * * * cd /path/to/web_app && python scripts/populate_pl_daily.py >> logs/pl_etl.log 2>&1
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


# ── 4G Aggregation ─────────────────────────────────────────────────────────────
SQL_4G_UPSERT = """
INSERT INTO "4G_pl_hy_daily"
    (date, nsa, city, cluster, siteid,
     packet_loss_num, packet_loss_denum,
     latency_sum, latency_count,
     jitter_sum, jitter_count,
     tx_packets, rx_packets)
SELECT
    date,
    COALESCE(nsa, 'Unknown')     AS nsa,
    COALESCE(city, 'Unknown')    AS city,
    COALESCE(cluster, 'Unknown') AS cluster,
    siteid,
    SUM(packet_loss_num)                            AS packet_loss_num,
    SUM(packet_loss_denum)                          AS packet_loss_denum,
    SUM(COALESCE(latency, 0))                       AS latency_sum,
    COUNT(CASE WHEN latency IS NOT NULL THEN 1 END) AS latency_count,
    SUM(COALESCE(mean_delay_jitter, 0))             AS jitter_sum,
    COUNT(CASE WHEN mean_delay_jitter IS NOT NULL THEN 1 END) AS jitter_count,
    SUM(COALESCE(twamp_detect_packets_transmitted, 0)) AS tx_packets,
    SUM(COALESCE(twamp_detect_packets_received, 0))    AS rx_packets
FROM "4G_pl_hy"
WHERE date >= %s AND date <= %s
  AND siteid IS NOT NULL
GROUP BY date, nsa, city, cluster, siteid
ON CONFLICT (date, siteid) DO UPDATE SET
    nsa               = EXCLUDED.nsa,
    city              = EXCLUDED.city,
    cluster           = EXCLUDED.cluster,
    packet_loss_num   = EXCLUDED.packet_loss_num,
    packet_loss_denum = EXCLUDED.packet_loss_denum,
    latency_sum       = EXCLUDED.latency_sum,
    latency_count     = EXCLUDED.latency_count,
    jitter_sum        = EXCLUDED.jitter_sum,
    jitter_count      = EXCLUDED.jitter_count,
    tx_packets        = EXCLUDED.tx_packets,
    rx_packets        = EXCLUDED.rx_packets
"""


# ── 2G Aggregation ─────────────────────────────────────────────────────────────
SQL_2G_UPSERT = """
INSERT INTO "2G_pl_hy_daily"
    (date, nsa, city, cluster, siteid,
     packet_loss_num, packet_loss_denum,
     latency_sum, latency_count,
     jitter_sum, jitter_count)
SELECT
    "Date"                                                   AS date,
    COALESCE(nsa, 'Unknown')                                 AS nsa,
    COALESCE(city, 'Unknown')                                AS city,
    COALESCE(cluster, 'Unknown')                             AS cluster,
    "Site ID"                                                AS siteid,
    SUM("Packet Loss Rate Num")                              AS packet_loss_num,
    SUM("Packet Loss Rate Denum")                            AS packet_loss_denum,
    SUM(COALESCE("Mean round-trip delay(ms)", 0))            AS latency_sum,
    COUNT(CASE WHEN "Mean round-trip delay(ms)" IS NOT NULL THEN 1 END) AS latency_count,
    SUM(COALESCE("Mean delay jitter(ms)", 0))                AS jitter_sum,
    COUNT(CASE WHEN "Mean delay jitter(ms)" IS NOT NULL THEN 1 END) AS jitter_count
FROM "2G_pl_hy"
WHERE "Date" >= %s AND "Date" <= %s
  AND "Site ID" IS NOT NULL
GROUP BY "Date", nsa, city, cluster, "Site ID"
ON CONFLICT (date, siteid) DO UPDATE SET
    nsa               = EXCLUDED.nsa,
    city              = EXCLUDED.city,
    cluster           = EXCLUDED.cluster,
    packet_loss_num   = EXCLUDED.packet_loss_num,
    packet_loss_denum = EXCLUDED.packet_loss_denum,
    latency_sum       = EXCLUDED.latency_sum,
    latency_count     = EXCLUDED.latency_count,
    jitter_sum        = EXCLUDED.jitter_sum,
    jitter_count      = EXCLUDED.jitter_count
"""


# ── Helpers ────────────────────────────────────────────────────────────────────
def get_max_daily_date(conn, table):
    """Return MAX(date) from the daily table, or None if empty."""
    with conn.cursor() as cur:
        cur.execute('SELECT MAX(date) FROM "{}"'.format(table))
        row = cur.fetchone()
        return row[0] if row else None


def get_max_hourly_date(conn, table, date_col):
    """Return MAX(date_col) from the raw hourly table."""
    with conn.cursor() as cur:
        cur.execute('SELECT MAX("{}") FROM "{}"'.format(date_col, table))
        row = cur.fetchone()
        return row[0] if row else None


def run_upsert(conn, sql, start, end, batch_days=30, label=""):
    """Run an upsert SQL in batches of batch_days to avoid locking for too long."""
    total_rows = 0
    current = start
    while current <= end:
        batch_end = min(current + timedelta(days=batch_days - 1), end)
        with conn.cursor() as cur:
            cur.execute(sql, (current, batch_end))
            rows = cur.rowcount
        conn.commit()
        total_rows += rows
        log.info("  [{}] {} -> {}: {:,} rows upserted".format(label, current, batch_end, rows))
        current = batch_end + timedelta(days=1)
    return total_rows


# ── Main ────────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Populate 4G/2G PL daily tables from hourly raw data.")
    parser.add_argument(
        "--start-date",
        default=None,
        help="Start date for backfill/recompute (YYYY-MM-DD). Default: day after MAX daily date."
    )
    parser.add_argument(
        "--end-date",
        default=None,
        help="End date (YYYY-MM-DD). Default: MAX date in raw hourly table."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Force upsert even if daily table already has data for the date range."
    )
    parser.add_argument(
        "--tech",
        choices=["4G", "2G", "ALL"],
        default="ALL",
        help="Which technology to process. Default: ALL"
    )
    parser.add_argument(
        "--batch-days",
        type=int,
        default=30,
        help="Number of days per DB transaction batch. Default: 30"
    )
    args = parser.parse_args()

    log.info("=" * 60)
    log.info("PL Daily ETL -- Starting")
    log.info("Tech: {} | Force: {}".format(args.tech, args.force))
    log.info("=" * 60)

    conn = get_conn()

    try:
        # ── Process 4G ────────────────────────────────────────────────────
        if args.tech in ("4G", "ALL"):
            log.info("--- Processing 4G ---")

            max_daily  = get_max_daily_date(conn, "4G_pl_hy_daily")
            max_hourly = get_max_hourly_date(conn, "4G_pl_hy", "date")

            if max_hourly is None:
                log.warning("4G_pl_hy is empty, skipping 4G.")
            else:
                if args.start_date:
                    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
                elif max_daily is None:
                    start = date(2026, 1, 1)
                    log.info("No daily data yet. Using default backfill start: {}".format(start))
                elif args.force:
                    start = max_daily
                else:
                    # Incremental: re-process last 2 days to catch late-arriving raw data
                    start = max_daily - timedelta(days=2)

                end = (
                    datetime.strptime(args.end_date, "%Y-%m-%d").date()
                    if args.end_date
                    else max_hourly
                )

                log.info("4G range: {} -> {}  (hourly max: {}, daily max: {})".format(
                    start, end, max_hourly, max_daily))

                if start > end:
                    log.info("4G daily table is up to date. Nothing to do.")
                else:
                    rows = run_upsert(conn, SQL_4G_UPSERT, start, end, args.batch_days, "4G")
                    log.info("4G total upserted: {:,} rows".format(rows))

        # ── Process 2G ────────────────────────────────────────────────────
        if args.tech in ("2G", "ALL"):
            log.info("--- Processing 2G ---")

            max_daily  = get_max_daily_date(conn, "2G_pl_hy_daily")
            max_hourly = get_max_hourly_date(conn, "2G_pl_hy", "Date")

            if max_hourly is None:
                log.warning("2G_pl_hy is empty, skipping 2G.")
            else:
                if args.start_date:
                    start = datetime.strptime(args.start_date, "%Y-%m-%d").date()
                elif max_daily is None:
                    start = date(2026, 1, 1)
                    log.info("No daily data yet. Using default backfill start: {}".format(start))
                elif args.force:
                    start = max_daily
                else:
                    start = max_daily - timedelta(days=2)

                end = (
                    datetime.strptime(args.end_date, "%Y-%m-%d").date()
                    if args.end_date
                    else max_hourly
                )

                log.info("2G range: {} -> {}  (hourly max: {}, daily max: {})".format(
                    start, end, max_hourly, max_daily))

                if start > end:
                    log.info("2G daily table is up to date. Nothing to do.")
                else:
                    rows = run_upsert(conn, SQL_2G_UPSERT, start, end, args.batch_days, "2G")
                    log.info("2G total upserted: {:,} rows".format(rows))

    except Exception as e:
        conn.rollback()
        log.error("ETL failed: {}".format(e), exc_info=True)
        sys.exit(1)
    finally:
        conn.close()

    log.info("=" * 60)
    log.info("PL Daily ETL -- Completed")
    log.info("=" * 60)


if __name__ == "__main__":
    main()
