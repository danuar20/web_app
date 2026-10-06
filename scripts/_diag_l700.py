"""Diagnose: L700 data presence + query timing for Unbalance PRB."""
import os
import time
import psycopg2
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

conn = psycopg2.connect(
    dbname=os.environ["POSTGRES_DB_NAME"],
    user=os.environ["POSTGRES_DB_USER"],
    password=os.environ["POSTGRES_DB_PASSWORD"],
    host=os.environ["POSTGRES_DB_HOST"],
    port=os.environ["POSTGRES_DB_PORT"],
)
cur = conn.cursor()

print("=== non-null count per band col (W35..W39) ===")
cur.execute("""SELECT column_name FROM information_schema.columns
               WHERE table_name='unbalance_prb_weekly'
                 AND (column_name LIKE 'dl\\_%' OR column_name LIKE 'ul\\_%')
               ORDER BY ordinal_position""")
cols = [r[0] for r in cur.fetchall()]
for c in cols:
    cur.execute(f'SELECT COUNT(*) FROM "unbalance_prb_weekly" WHERE week BETWEEN %s AND %s AND "{c}" IS NOT NULL',
                ["2026-W35", "2026-W39"])
    print(f"{c:14s} non-null = {cur.fetchone()[0]}")

print("\n=== dl_L700 sample rows W37 ===")
cur.execute("""SELECT week, site_id, sector, dl_L700, ul_L700 FROM "unbalance_prb_weekly"
               WHERE week = '2026-W37' AND dl_L700 IS NOT NULL LIMIT 5""")
for r in cur.fetchall():
    print(r)

print("\n=== timing: data query fetch (3 runs) ===")
BANDS = ["L700", "L900", "L1800", "L2100", "L2300_1", "L2300_2", "L2300_3",
         "L2600_1", "L2600_2", "L2600_3"]
dl_cols = ", ".join(f'"dl_{b}"' for b in BANDS)
ul_cols = ", ".join(f'"ul_{b}"' for b in BANDS)
sql = f'''SELECT week, COALESCE(site_id,''), COALESCE(site_id_v2,''), COALESCE(sector,''),
                 COALESCE(type,''), COALESCE(num_band,0),
                 {dl_cols}, avg_dl_prb, max_dl_prb, COALESCE(max_dl_band,''), COALESCE(min_dl_band,''),
                 {ul_cols}, avg_ul_prb, max_ul_prb, COALESCE(max_ul_band,''), COALESCE(min_ul_band,'')
          FROM "unbalance_prb_weekly"
          WHERE week >= %s AND week <= %s
          ORDER BY week, site_id, sector'''
for i in range(3):
    t0 = time.perf_counter()
    cur.execute(sql, ["2026-W35", "2026-W39"])
    rows = cur.fetchall()
    t1 = time.perf_counter()
    print(f"run {i+1}: rows={len(rows)} fetch={1000*(t1-t0):.1f} ms")

print("\n=== timing: weeks endpoint query ===")
t0 = time.perf_counter()
cur.execute('SELECT DISTINCT week FROM "unbalance_prb_weekly" ORDER BY week DESC')
weeks = cur.fetchall()
t1 = time.perf_counter()
print(f"distinct weeks={len(weeks)} time={1000*(t1-t0):.1f} ms")

print("\n=== table stats ===")
cur.execute("""SELECT relname, n_live_tup, pg_size_pretty(pg_total_relation_size(oid))
               FROM pg_class WHERE relname IN ('unbalance_prb_weekly','unbalance_prb')""")
for r in cur.fetchall():
    print(r)

conn.close()