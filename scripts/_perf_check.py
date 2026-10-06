"""Diagnose Unbalance PRB W35-W39 query performance."""
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

BANDS = ["L900", "L1800", "L2100", "L2300_1", "L2300_2", "L2300_3", "L700",
         "L2600_1", "L2600_2", "L2600_3"]
dl_cols = ", ".join(f'"dl_{b}"' for b in BANDS)
ul_cols = ", ".join(f'"ul_{b}"' for b in BANDS)

sql = f'''
    SELECT week, site_id, site_id_v2, sector, type, num_band,
           {dl_cols}, avg_dl_prb, max_dl_prb, max_dl_band, min_dl_band,
           {ul_cols}, avg_ul_prb, max_ul_prb, max_ul_band, min_ul_band
    FROM "unbalance_prb_weekly"
    WHERE week >= %s AND week <= %s
    ORDER BY week, site_id, sector
'''

print("=== EXPLAIN (W35..W39) ===")
cur.execute("EXPLAIN (ANALYZE, BUFFERS) " + sql, ["2026-W35", "2026-W39"])
for r in cur.fetchall():
    print(r[0])

print("\n=== timing: W35..W39 full fetch ===")
t0 = time.perf_counter()
cur.execute(sql, ["2026-W35", "2026-W39"])
rows = cur.fetchall()
t1 = time.perf_counter()
print(f"rows={len(rows)}  db_time={1000*(t1-t0):.1f} ms  cols={len(rows[0]) if rows else 0}")

print("\n=== indexes on unbalance_prb_weekly ===")
cur.execute("SELECT indexname, indexdef FROM pg_indexes WHERE tablename='unbalance_prb_weekly'")
for r in cur.fetchall():
    print(r[0], "->", r[1][:110])

print("\n=== jsonify size estimate ===")
import json
payload = {"columns": BANDS, "rows": rows}
s = json.dumps(payload, default=str)
print(f"json bytes = {len(s)/1024/1024:.2f} MB")

print("\n=== get_available_bands (information_schema) timing ===")
t0 = time.perf_counter()
cur.execute("""SELECT column_name FROM information_schema.columns
               WHERE table_name='unbalance_prb_weekly' AND column_name LIKE 'dl\\_%'""")
bands = [r[0] for r in cur.fetchall()]
t1 = time.perf_counter()
print(f"bands={[b.replace('dl_','') for b in bands]}  time={1000*(t1-t0):.1f} ms")

conn.close()