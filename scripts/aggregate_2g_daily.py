import sys
import os
import argparse
from datetime import datetime, timedelta
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

# Connect to postgres using the same config as the web app
# Add the app directory to sys.path so we can import get_postgres_connection
sys.path.append(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'app'))

# Instead of importing the flask app's db connection (which might need app context),
# we'll define a standalone connection using standard environment variables or defaults
def get_conn():
    return psycopg2.connect(
        dbname=os.environ.get("POSTGRES_DB_NAME", "postgres"),
        user=os.environ.get("POSTGRES_DB_USER", "postgres"),
        password=os.environ.get("POSTGRES_DB_PASSWORD", "1234"),
        host=os.environ.get("POSTGRES_DB_HOST", "localhost"),
        port=os.environ.get("POSTGRES_DB_PORT", "5432")
    )

def create_table_if_not_exists(conn):
    cur = conn.cursor()
    print("Ensuring 2g_kpi_zte_daily table exists...")
    sql = """
    CREATE TABLE IF NOT EXISTS "2g_kpi_zte_daily" (
        kpi_date DATE NOT NULL,
        nsa VARCHAR(255),
        city VARCHAR(255),
        me_name VARCHAR(255),
        siteid VARCHAR(255),
        bts_name VARCHAR(255),
        total_payload DOUBLE PRECISION,
        tch_traffic DOUBLE PRECISION,
        sdcch_traffic DOUBLE PRECISION,
        "Offic_full_traffic" DOUBLE PRECISION,
        "Offic_half_traffic" DOUBLE PRECISION,
        tch_avail_num DOUBLE PRECISION,
        tch_avail_denum DOUBLE PRECISION,
        cssr_num DOUBLE PRECISION,
        cssr_denum DOUBLE PRECISION,
        "2g_ccsr_num" DOUBLE PRECISION,
        "2g_ccsr_denum" DOUBLE PRECISION,
        hosr_num DOUBLE PRECISION,
        hosr_denum DOUBLE PRECISION,
        sdsr_num DOUBLE PRECISION,
        sdsr_denum DOUBLE PRECISION,
        tbf_dl_est_num DOUBLE PRECISION,
        tbf_dl_est_denum DOUBLE PRECISION,
        tbf_comp_num DOUBLE PRECISION,
        tbf_comp_denum DOUBLE PRECISION,
        tch_drop_num DOUBLE PRECISION,
        tch_drop_denum DOUBLE PRECISION,
        tch_block_num DOUBLE PRECISION,
        tch_block_denum DOUBLE PRECISION,
        sdcch_block_num DOUBLE PRECISION,
        sdcch_block_denum DOUBLE PRECISION,
        fastreturn_to_lte DOUBLE PRECISION,
        icm_band35_num DOUBLE PRECISION,
        icm_band35_denum DOUBLE PRECISION,
        num_icm_interference_ono DOUBLE PRECISION,
        denum_icm_interference_ono DOUBLE PRECISION,
        mos_dl DOUBLE PRECISION,
        mos_ul DOUBLE PRECISION,
        sd_to_tch DOUBLE PRECISION,
        cst DOUBLE PRECISION,
        pdch_alocation_failure_rate_num DOUBLE PRECISION,
        pdch_alocation_failure_rate_denum DOUBLE PRECISION,
        num_ul_qual_0_5 DOUBLE PRECISION,
        denum_ul_qual DOUBLE PRECISION,
        num_dl_qual_0_5 DOUBLE PRECISION,
        denum_dl_qual_0_5 DOUBLE PRECISION,
        gprs_dl_thp DOUBLE PRECISION,
        edge_dl_thp DOUBLE PRECISION,
        gprs_payload DOUBLE PRECISION,
        edge_payload DOUBLE PRECISION,
        CONSTRAINT unique_2g_kpi_daily UNIQUE (kpi_date, nsa, city, me_name, siteid, bts_name)
    );
    """
    cur.execute(sql)
    
    # Create indexes for fast querying
    cur.execute('CREATE INDEX IF NOT EXISTS idx_2g_kpi_daily_date ON "2g_kpi_zte_daily"(kpi_date);')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_2g_kpi_daily_dims ON "2g_kpi_zte_daily"(nsa, city, me_name, siteid, bts_name);')
    
    conn.commit()
    cur.close()
    print("Table ready.")

def aggregate_date_range(conn, start_date, end_date):
    cur = conn.cursor()
    print(f"Aggregating 2G data from {start_date} to {end_date}...")

    cur.execute('DELETE FROM "2g_kpi_zte_daily" WHERE kpi_date BETWEEN %s AND %s', [start_date, end_date])

    cur.execute("SET work_mem = '2GB'")
    sql = """
    INSERT INTO "2g_kpi_zte_daily" (
        kpi_date, nsa, city, me_name, siteid, bts_name,
        total_payload, tch_traffic, sdcch_traffic, "Offic_full_traffic", "Offic_half_traffic",
        tch_avail_num, tch_avail_denum, cssr_num, cssr_denum, "2g_ccsr_num", "2g_ccsr_denum",
        hosr_num, hosr_denum, sdsr_num, sdsr_denum, tbf_dl_est_num, tbf_dl_est_denum,
        tbf_comp_num, tbf_comp_denum, tch_drop_num, tch_drop_denum, tch_block_num, tch_block_denum,
        sdcch_block_num, sdcch_block_denum, fastreturn_to_lte, icm_band35_num, icm_band35_denum,
        num_icm_interference_ono, denum_icm_interference_ono, mos_dl, mos_ul, sd_to_tch, cst, pdch_alocation_failure_rate_num, pdch_alocation_failure_rate_denum,
        num_ul_qual_0_5, denum_ul_qual, num_dl_qual_0_5, denum_dl_qual_0_5, gprs_dl_thp, edge_dl_thp, gprs_payload, edge_payload
    )
    SELECT 
        DATE(datehour) as kpi_date,
        nsa,
        city,
        me_name,
        siteid,
        bts_name,
        SUM(total_payload), SUM(tch_traffic), SUM(sdcch_traffic), SUM("Offic_full_traffic"), SUM("Offic_half_traffic"),
        SUM(tch_avail_num), SUM(tch_avail_denum), SUM(cssr_num), SUM(cssr_denum), SUM("2g_ccsr_num"), SUM("2g_ccsr_denum"),
        SUM(hosr_num), SUM(hosr_denum), SUM(sdsr_num), SUM(sdsr_denum), SUM(tbf_dl_est_num), SUM(tbf_dl_est_denum),
        SUM(tbf_comp_num), SUM(tbf_comp_denum), SUM(tch_drop_num), SUM(tch_drop_denum), SUM(tch_block_num), SUM(tch_block_denum),
        SUM(sdcch_block_num), SUM(sdcch_block_denum), SUM(fastreturn_to_lte), SUM(icm_band35_num), SUM(icm_band35_denum),
        SUM(num_icm_interference_ono), SUM(denum_icm_interference_ono), AVG(mos_dl), AVG(mos_ul), AVG(sd_to_tch), AVG(cst), SUM(pdch_alocation_failure_rate_num), SUM(pdch_alocation_failure_rate_denum),
        SUM(num_ul_qual_0_5), SUM(denum_ul_qual), SUM(num_dl_qual_0_5), SUM(denum_dl_qual_0_5), AVG(gprs_dl_thp), AVG(edge_dl_thp), SUM(gprs_payload), SUM(edge_payload)
    FROM "2g_kpi_zte"
    WHERE DATE(datehour) BETWEEN %s AND %s
      AND nsa IS NOT NULL
      AND city IS NOT NULL
      AND me_name IS NOT NULL
      AND siteid IS NOT NULL
      AND bts_name IS NOT NULL
    GROUP BY DATE(datehour), nsa, city, me_name, siteid, bts_name;
    """

    cur.execute(sql, [start_date, end_date])
    cur.execute("RESET work_mem")
    inserted = cur.rowcount
    conn.commit()
    cur.close()
    print(f"-> Inserted {inserted} daily cell-level records for {start_date} to {end_date}.")


def main():
    parser = argparse.ArgumentParser(description="Aggregate 2G KPI data from hourly to daily.")
    parser.add_argument("--days", type=int, default=1, help="Number of days to backfill from the latest date (default: 1)")
    parser.add_argument("--date", type=str, help="Specific date to aggregate (YYYY-MM-DD)")
    parser.add_argument("--start-date", type=str, help="Start date to aggregate from (YYYY-MM-DD)")
    args = parser.parse_args()

    try:
        conn = get_conn()
    except Exception as e:
        print(f"Failed to connect to database: {e}")
        return

    create_table_if_not_exists(conn)

    if args.start_date:
        cur = conn.cursor()
        cur.execute('SELECT MAX(DATE(datehour)) FROM "2g_kpi_zte"')
        max_date = cur.fetchone()[0]
        cur.close()

        if not max_date:
            print("No data found in 2g_kpi_zte.")
            conn.close()
            return

        start_date = datetime.strptime(args.start_date, "%Y-%m-%d").date()

        if start_date > max_date:
            print(f"Start date {start_date} is after max data date {max_date}.")
            conn.close()
            return

        aggregate_date_range(conn, start_date.strftime("%Y-%m-%d"), max_date.strftime("%Y-%m-%d"))

    elif args.date:
        aggregate_date_range(conn, args.date, args.date)
    else:
        cur = conn.cursor()
        cur.execute('SELECT MAX(DATE(datehour)) FROM "2g_kpi_zte"')
        max_raw_date = cur.fetchone()[0]
        cur.execute('SELECT MAX(kpi_date) FROM "2g_kpi_zte_daily"')
        max_daily_date = cur.fetchone()[0]
        cur.close()

        if not max_raw_date:
            print("No data found in 2g_kpi_zte.")
            conn.close()
            return

        if max_daily_date and max_daily_date < max_raw_date:
            print(f"Gap detected! Latest daily data is {max_daily_date}, latest raw data is {max_raw_date}.")
            aggregate_date_range(conn, (max_daily_date + timedelta(days=1)).strftime("%Y-%m-%d"), max_raw_date.strftime("%Y-%m-%d"))
        else:
            print(f"Found latest data date: {max_raw_date}")
            if args.days > 0:
                start_date = (max_raw_date - timedelta(days=args.days - 1)).strftime("%Y-%m-%d")
                end_date = max_raw_date.strftime("%Y-%m-%d")
                aggregate_date_range(conn, start_date, end_date)

    conn.close()
    print("Aggregation complete!")

if __name__ == "__main__":
    main()
