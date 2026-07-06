import sys
import os
import argparse
import psycopg2
from dotenv import load_dotenv

# Load environment variables from .env
load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), '.env'))

def get_conn():
    return psycopg2.connect(
        dbname=os.environ.get("POSTGRES_DB_NAME", "postgres"),
        user=os.environ.get("POSTGRES_DB_USER", "postgres"),
        password=os.environ.get("POSTGRES_DB_PASSWORD", "1234"),
        host=os.environ.get("POSTGRES_DB_HOST", "localhost"),
        port=os.environ.get("POSTGRES_DB_PORT", "5432")
    )

def create_materialized_views(conn):
    cur = conn.cursor()

    print("Creating mv_traffic_payload_daily_city...")
    cur.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_traffic_payload_daily_city AS
        SELECT
            "Date",
            "Year by Date",
            "KABUPATEN",
            "NSA",
            SUM("Payload (MB)") AS sum_payload_mb,
            SUM("Traffic (erlang)") AS sum_traffic_erl,
            SUM(CASE WHEN "Avail_Num" IS NOT NULL AND "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Num" END) AS sum_avail_num,
            SUM(CASE WHEN "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Denum" END) AS sum_avail_denum,
            SUM("Max_RRC_Conn_User") AS sum_max_rrc
        FROM traffic_payload
        WHERE "Date" IS NOT NULL
        GROUP BY "Date", "Year by Date", "KABUPATEN", "NSA"
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_city_date ON mv_traffic_payload_daily_city("Date");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_city_kab ON mv_traffic_payload_daily_city("KABUPATEN");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_city_nsa ON mv_traffic_payload_daily_city("NSA");')
    print("Created mv_traffic_payload_daily_city.")


    print("Creating mv_traffic_payload_daily_site...")
    cur.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_traffic_payload_daily_site AS
        SELECT
            "Date",
            "Year by Date",
            "Site ID",
            "KABUPATEN",
            "NSA",
            SUM("Payload (MB)") AS sum_payload_mb,
            SUM("Traffic (erlang)") AS sum_traffic_erl,
            SUM(CASE WHEN "Avail_Num" IS NOT NULL AND "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Num" END) AS sum_avail_num,
            SUM(CASE WHEN "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Denum" END) AS sum_avail_denum,
            SUM("Max_RRC_Conn_User") AS sum_max_rrc
        FROM traffic_payload
        WHERE "Date" IS NOT NULL
        GROUP BY "Date", "Year by Date", "Site ID", "KABUPATEN", "NSA"
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_site_date ON mv_traffic_payload_daily_site("Date");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_site_id ON mv_traffic_payload_daily_site("Site ID");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_site_kab ON mv_traffic_payload_daily_site("KABUPATEN");')
    print("Created mv_traffic_payload_daily_site.")


    print("Creating mv_traffic_payload_yw_city...")
    cur.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_traffic_payload_yw_city AS
        SELECT
            "Y_W",
            "KABUPATEN",
            "NSA",
            SUM("Payload (MB)") AS sum_payload_mb,
            SUM("Traffic (erlang)") AS sum_traffic_erl,
            SUM(CASE WHEN "Avail_Num" IS NOT NULL AND "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Num" END) AS sum_avail_num,
            SUM(CASE WHEN "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Denum" END) AS sum_avail_denum,
            SUM("Max_RRC_Conn_User") AS sum_max_rrc
        FROM traffic_payload
        WHERE "Y_W" IS NOT NULL
        GROUP BY "Y_W", "KABUPATEN", "NSA"
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_yw_city_yw ON mv_traffic_payload_yw_city("Y_W");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_yw_city_kab ON mv_traffic_payload_yw_city("KABUPATEN");')
    print("Created mv_traffic_payload_yw_city.")


    print("Creating mv_traffic_payload_yw_site...")
    cur.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_traffic_payload_yw_site AS
        SELECT
            "Y_W",
            "Site ID",
            "KABUPATEN",
            "NSA",
            SUM("Payload (MB)") AS sum_payload_mb,
            SUM("Traffic (erlang)") AS sum_traffic_erl,
            SUM(CASE WHEN "Avail_Num" IS NOT NULL AND "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Num" END) AS sum_avail_num,
            SUM(CASE WHEN "Avail_Denum" IS NOT NULL AND "Avail_Denum" > 0 THEN "Avail_Denum" END) AS sum_avail_denum,
            SUM("Max_RRC_Conn_User") AS sum_max_rrc
        FROM traffic_payload
        WHERE "Y_W" IS NOT NULL
        GROUP BY "Y_W", "Site ID", "KABUPATEN", "NSA"
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_yw_site_yw ON mv_traffic_payload_yw_site("Y_W");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_yw_site_id ON mv_traffic_payload_yw_site("Site ID");')
    print("Created mv_traffic_payload_yw_site.")


    print("Creating mv_traffic_payload_daily_regional...")
    cur.execute("""
        CREATE MATERIALIZED VIEW IF NOT EXISTS mv_traffic_payload_daily_regional AS
        SELECT
            "Date",
            "Year by Date",
            "Regional",
            "NSA",
            "TO",
            SUM("Payload (MB)") AS sum_payload_mb,
            SUM("Traffic (erlang)") AS sum_traffic_erl
        FROM traffic_payload
        WHERE "Date" IS NOT NULL
        GROUP BY "Date", "Year by Date", "Regional", "NSA", "TO"
    """)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_reg_date ON mv_traffic_payload_daily_regional("Date");')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_mv_daily_reg_year ON mv_traffic_payload_daily_regional("Year by Date");')
    print("Created mv_traffic_payload_daily_regional.")

    conn.commit()
    cur.close()
    print("All materialized views created successfully!")

def refresh_views(conn):
    cur = conn.cursor()
    views = [
        "mv_traffic_payload_daily_city",
        "mv_traffic_payload_daily_site",
        "mv_traffic_payload_yw_city",
        "mv_traffic_payload_yw_site",
        "mv_traffic_payload_daily_regional"
    ]
    for view in views:
        print(f"Refreshing {view}...")
        cur.execute(f"REFRESH MATERIALIZED VIEW {view};")
    conn.commit()
    cur.close()
    print("All views refreshed!")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--refresh", action="store_true", help="Refresh existing views instead of creating them")
    args = parser.parse_args()

    try:
        conn = get_conn()
        if args.refresh:
            refresh_views(conn)
        else:
            create_materialized_views(conn)
        conn.close()
    except Exception as e:
        print(f"Error: {e}")
