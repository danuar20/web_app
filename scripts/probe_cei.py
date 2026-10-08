"""Probe sow.cei_score to validate CEI dashboard aggregations."""
import os
import sys
sys.path.insert(0, os.getcwd())
from dotenv import load_dotenv
load_dotenv(os.path.join(os.getcwd(), ".env"))
import psycopg2

KQIS = [
    ("web_rtt", "latest_week_only_web_browsing_client_side_round_trip_time_ms_hi"),
    ("web_ul_retrans", "latest_week_only_web_browsing_ul_retransmitted_packet_rate_hit_"),
    ("video_vxb", "latest_week_only_streaming_video_streaming_xkb_start_delay_s_hi"),
    ("voip_ul", "latest_week_only_voip_udp_uplink_jitter_ms_hit_count"),
    ("voip_dl", "latest_week_only_voip_udp_downlink_jitter_ms_hit_count"),
    ("game_rtt", "latest_week_only_gamemax_client_side_round_trip_time_ms_hit_cou"),
    ("game_jitter", "latest_week_only_gamemax_udp_uplink_jitter_ms_hit_count"),
]


def main():
    conn = psycopg2.connect(
        host=os.getenv("POSTGRES_DB_HOST"), database=os.getenv("POSTGRES_DB_NAME"),
        user=os.getenv("POSTGRES_DB_USER"), password=os.getenv("POSTGRES_DB_PASSWORD"),
        port=os.getenv("POSTGRES_DB_PORT", "5432"), connect_timeout=10)
    cur = conn.cursor()

    print("=== % good cell per week (region PUMA) ===")
    cur.execute("""
        SELECT weeknum,
               COUNT(*) AS total,
               COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') AS good,
               ROUND(COUNT(*) FILTER (WHERE remark_cell = 'Good_cell') * 100.0
                     / NULLIF(COUNT(*), 0), 2) AS pct
        FROM sow.cei_score
        GROUP BY weeknum ORDER BY weeknum DESC LIMIT 12
    """)
    for r in cur.fetchall():
        print("  ", r)

    print("\n=== bad cell count latest week ===")
    cur.execute("""
        SELECT weeknum,
               COUNT(*) FILTER (WHERE remark_cell = 'Bad_cell') AS bad
        FROM sow.cei_score GROUP BY weeknum ORDER BY weeknum DESC LIMIT 6
    """)
    for r in cur.fetchall():
        print("  ", r)

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
