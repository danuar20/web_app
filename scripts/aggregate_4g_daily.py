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
    print("Ensuring 4g_kpi_zte_daily table exists...")
    sql = '''
    CREATE TABLE IF NOT EXISTS "4g_kpi_zte_daily" (
        kpi_date DATE NOT NULL,
        nsa VARCHAR(255),
        city VARCHAR(255),
        subnetwork_name VARCHAR(255),
        siteid VARCHAR(255),
        cell_name VARCHAR(255),
        "4g_payload_mb" DOUBLE PRECISION,
        dl_traffic_volume DOUBLE PRECISION,
        ul_traffic_volume DOUBLE PRECISION,
        dl_payload_ca_mbyte DOUBLE PRECISION,
        ul_payload_ca_mbyte DOUBLE PRECISION,
        cssr_num DOUBLE PRECISION,
        cssr_denum DOUBLE PRECISION,
        volte_traffic DOUBLE PRECISION,
        max_rrc_conn_user DOUBLE PRECISION,
        new_active_users DOUBLE PRECISION,
        dl_prb_util_num DOUBLE PRECISION,
        dl_prb_util_denum DOUBLE PRECISION,
        ul_prb_util_num DOUBLE PRECISION,
        ul_prb_util_denum DOUBLE PRECISION,
        user_dl_thp_num DOUBLE PRECISION,
        user_dl_thp_denum DOUBLE PRECISION,
        user_ul_thp_num DOUBLE PRECISION,
        user_ul_thp_denum DOUBLE PRECISION,
        avail_num DOUBLE PRECISION,
        avail_denum DOUBLE PRECISION,
        erab_setup_num DOUBLE PRECISION,
        erab_setup_denum DOUBLE PRECISION,
        rrc_setup_num DOUBLE PRECISION,
        rrc_setup_denum DOUBLE PRECISION,
        s1_signaling_sr_num DOUBLE PRECISION,
        s1_signaling_sr_denum DOUBLE PRECISION,
        sdr_num DOUBLE PRECISION,
        sdr_denum DOUBLE PRECISION,
        ifho_num DOUBLE PRECISION,
        ifho_denum DOUBLE PRECISION,
        csfb_num DOUBLE PRECISION,
        csfb_denum DOUBLE PRECISION,
        se_v3_num DOUBLE PRECISION,
        se_v3_denum DOUBLE PRECISION,
        num_average_cqi DOUBLE PRECISION,
        denum_average_cqi DOUBLE PRECISION,
        inta_rat_ifho_num DOUBLE PRECISION,
        inta_rat_ifho_denum DOUBLE PRECISION,
        num_dl_avg_mcs DOUBLE PRECISION,
        denum_dl_avg_mcs DOUBLE PRECISION,
        num_ul_avg_mcs DOUBLE PRECISION,
        denum_ul_avg_mcs DOUBLE PRECISION,
        num_agg8 DOUBLE PRECISION,
        denum_agg8 DOUBLE PRECISION,
        srvcc_gsm_num DOUBLE PRECISION,
        srvcc_gsm_denum DOUBLE PRECISION,
        volte_call_drop_rate_mme_num DOUBLE PRECISION,
        volte_call_drop_rate_mme_denum DOUBLE PRECISION,
        erab_drop_num DOUBLE PRECISION,
        erab_drop_denum DOUBLE PRECISION,
        processing_delay_num DOUBLE PRECISION,
        processing_delay_denum DOUBLE PRECISION,
        "DL_CCE_Failure_Num" DOUBLE PRECISION,
        "DL_CCE_Failure_Denum" DOUBLE PRECISION,
        "UL_CCE_Failure_Num" DOUBLE PRECISION,
        "UL_CCE_Failure_Denum" DOUBLE PRECISION,
        num_rsrp_dbm DOUBLE PRECISION,
        denum_rsrp_dbm DOUBLE PRECISION,
        "Good_RSRP (>-105) Ratio Num" DOUBLE PRECISION,
        "Good_RSRP (>-105) Ratio Denum" DOUBLE PRECISION,
        average_cpu_utilization DOUBLE PRECISION,
        peak_cpu_utilization DOUBLE PRECISION,
        avg_rsrp_dbm DOUBLE PRECISION,
        "Average of RSRQ Value of Serving Cell(period measurement)(dB)" DOUBLE PRECISION,
        avg_cell_rssi DOUBLE PRECISION,
        average_ni_of_carrier DOUBLE PRECISION,
        pucch_avg_ni_of_carrier DOUBLE PRECISION,
        pusch_avg_ni_of_carrier DOUBLE PRECISION,
        cell_uplink_init_bler DOUBLE PRECISION,
        cell_downlink_init_bler DOUBLE PRECISION,
        number_of_paging_records_received_by_the_enodeb DOUBLE PRECISION,
        number_of_paging_records_discarded_at_the_enodeb DOUBLE PRECISION,
        "Number of Outgoing HO Preparation Attempts(based UL Service)" DOUBLE PRECISION,
        "Number of Outgoing HO Success(based UL Service)" DOUBLE PRECISION,
        CONSTRAINT unique_4g_kpi_daily UNIQUE (kpi_date, nsa, city, subnetwork_name, siteid, cell_name)
    );
    '''
    cur.execute(sql)
    cur.execute('CREATE INDEX IF NOT EXISTS idx_4g_kpi_daily_date ON "4g_kpi_zte_daily"(kpi_date);')
    cur.execute('CREATE INDEX IF NOT EXISTS idx_4g_kpi_daily_dims ON "4g_kpi_zte_daily"(nsa, city, subnetwork_name, siteid, cell_name);')
    conn.commit()
    cur.close()
    print("Table ready.")


def aggregate_date_range(conn, start_date, end_date):
    cur = conn.cursor()
    print(f"Aggregating 4G data from {start_date} to {end_date}...")

    cur.execute('DELETE FROM "4g_kpi_zte_daily" WHERE kpi_date BETWEEN %s AND %s', [start_date, end_date])

    cur.execute("SET work_mem = '2GB'")
    sql = '''
    INSERT INTO "4g_kpi_zte_daily" (
        kpi_date, nsa, city, subnetwork_name, siteid, cell_name,
        "4g_payload_mb", dl_traffic_volume, ul_traffic_volume,
        dl_payload_ca_mbyte, ul_payload_ca_mbyte,
        cssr_num, cssr_denum, volte_traffic,
        max_rrc_conn_user, new_active_users,
        dl_prb_util_num, dl_prb_util_denum,
        ul_prb_util_num, ul_prb_util_denum,
        user_dl_thp_num, user_dl_thp_denum,
        user_ul_thp_num, user_ul_thp_denum,
        avail_num, avail_denum,
        erab_setup_num, erab_setup_denum,
        rrc_setup_num, rrc_setup_denum,
        s1_signaling_sr_num, s1_signaling_sr_denum,
        sdr_num, sdr_denum,
        ifho_num, ifho_denum,
        csfb_num, csfb_denum,
        se_v3_num, se_v3_denum,
        num_average_cqi, denum_average_cqi,
        inta_rat_ifho_num, inta_rat_ifho_denum,
        num_dl_avg_mcs, denum_dl_avg_mcs,
        num_ul_avg_mcs, denum_ul_avg_mcs,
        num_agg8, denum_agg8,
        srvcc_gsm_num, srvcc_gsm_denum,
        volte_call_drop_rate_mme_num, volte_call_drop_rate_mme_denum,
        erab_drop_num, erab_drop_denum,
        processing_delay_num, processing_delay_denum,
        "DL_CCE_Failure_Num", "DL_CCE_Failure_Denum",
        "UL_CCE_Failure_Num", "UL_CCE_Failure_Denum",
        num_rsrp_dbm, denum_rsrp_dbm,
        "Good_RSRP (>-105) Ratio Num", "Good_RSRP (>-105) Ratio Denum",
        "Number of Outgoing HO Preparation Attempts(based UL Service)",
        "Number of Outgoing HO Success(based UL Service)",
        average_cpu_utilization, peak_cpu_utilization,
        avg_rsrp_dbm, "Average of RSRQ Value of Serving Cell(period measurement)(dB)", avg_cell_rssi,
        average_ni_of_carrier, pucch_avg_ni_of_carrier,
        pusch_avg_ni_of_carrier,
        cell_uplink_init_bler, cell_downlink_init_bler,
        number_of_paging_records_received_by_the_enodeb,
        number_of_paging_records_discarded_at_the_enodeb
    )
    SELECT
        date AS kpi_date,
        nsa,
        city,
        subnetwork_name,
        siteid,
        cell_name,
        SUM("4g_payload_mb"), SUM(dl_traffic_volume), SUM(ul_traffic_volume),
        SUM(dl_payload_ca_mbyte), SUM(ul_payload_ca_mbyte),
        SUM(cssr_num), SUM(cssr_denum), SUM(volte_traffic),
        SUM(max_rrc_conn_user), SUM(new_active_users),
        SUM(dl_prb_util_num), SUM(dl_prb_util_denum),
        SUM(ul_prb_util_num), SUM(ul_prb_util_denum),
        SUM(user_dl_thp_num), SUM(user_dl_thp_denum),
        SUM(user_ul_thp_num), SUM(user_ul_thp_denum),
        SUM(avail_num), SUM(avail_denum),
        SUM(erab_setup_num), SUM(erab_setup_denum),
        SUM(rrc_setup_num), SUM(rrc_setup_denum),
        SUM(s1_signaling_sr_num), SUM(s1_signaling_sr_denum),
        SUM(sdr_num), SUM(sdr_denum),
        SUM(ifho_num), SUM(ifho_denum),
        SUM(csfb_num), SUM(csfb_denum),
        SUM(se_v3_num), SUM(se_v3_denum),
        SUM(num_average_cqi), SUM(denum_average_cqi),
        SUM(inta_rat_ifho_num), SUM(inta_rat_ifho_denum),
        SUM(num_dl_avg_mcs), SUM(denum_dl_avg_mcs),
        SUM(num_ul_avg_mcs), SUM(denum_ul_avg_mcs),
        SUM(num_agg8), SUM(denum_agg8),
        SUM(srvcc_gsm_num), SUM(srvcc_gsm_denum),
        SUM(volte_call_drop_rate_mme_num), SUM(volte_call_drop_rate_mme_denum),
        SUM(erab_drop_num), SUM(erab_drop_denum),
        SUM(processing_delay_num), SUM(processing_delay_denum),
        SUM("DL_CCE_Failure_Num"), SUM("DL_CCE_Failure_Denum"),
        SUM("UL_CCE_Failure_Num"), SUM("UL_CCE_Failure_Denum"),
        SUM(num_rsrp_dbm), SUM(denum_rsrp_dbm),
        SUM("Good_RSRP (>-105) Ratio Num"), SUM("Good_RSRP (>-105) Ratio Denum"),
        SUM("Number of Outgoing HO Preparation Attempts(based UL Service)"), SUM("Number of Outgoing HO Success(based UL Service)"),
        AVG(average_cpu_utilization), AVG(peak_cpu_utilization),
        AVG(avg_rsrp_dbm), AVG("Average of RSRQ Value of Serving Cell(period measurement)(dB)"), AVG(avg_cell_rssi),
        AVG(average_ni_of_carrier), AVG(pucch_avg_ni_of_carrier),
        AVG(pusch_avg_ni_of_carrier), AVG(cell_uplink_init_bler),
        AVG(cell_downlink_init_bler),
        SUM(number_of_paging_records_received_by_the_enodeb),
        SUM(number_of_paging_records_discarded_at_the_enodeb)
    FROM "4g_kpi_zte"
    WHERE date BETWEEN %s AND %s
      AND nsa IS NOT NULL
      AND city IS NOT NULL
      AND subnetwork_name IS NOT NULL
      AND siteid IS NOT NULL
      AND cell_name IS NOT NULL
    GROUP BY date, nsa, city, subnetwork_name, siteid, cell_name;
    '''

    cur.execute(sql, [start_date, end_date])
    cur.execute("RESET work_mem")
    inserted = cur.rowcount
    conn.commit()
    cur.close()
    print(f"-> Inserted {inserted} daily site-level records for {start_date} to {end_date}.")


def main():
    parser = argparse.ArgumentParser(description="Aggregate 4G KPI data from hourly to daily.")
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
        cur.execute('SELECT MAX(date) FROM "4g_kpi_zte"')
        max_date = cur.fetchone()[0]
        cur.close()

        if not max_date:
            print("No data found in 4g_kpi_zte.")
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
        cur.execute('SELECT MAX(date) FROM "4g_kpi_zte"')
        max_raw_date = cur.fetchone()[0]
        cur.execute('SELECT MAX(kpi_date) FROM "4g_kpi_zte_daily"')
        max_daily_date = cur.fetchone()[0]
        cur.close()

        if not max_raw_date:
            print("No data found in 4g_kpi_zte.")
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
