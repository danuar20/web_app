"""Verify param ordering hypothesis for dashboard_4g_tech query."""
import os
import time
import psycopg2
from dotenv import load_dotenv

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
load_dotenv(os.path.join(ROOT, ".env"))

conn = psycopg2.connect(
    dbname=os.environ["POSTGRES_DB_NAME"], user=os.environ["POSTGRES_DB_USER"],
    password=os.environ["POSTGRES_DB_PASSWORD"], host=os.environ["POSTGRES_DB_HOST"],
    port=os.environ["POSTGRES_DB_PORT"])
cur = conn.cursor()

band_mapping = """
    CASE RIGHT(cell::text, 1)
        WHEN '1' THEN 'L1800'
        WHEN '2' THEN 'L900'
        WHEN '3' THEN 'L2100'
        WHEN '4' THEN 'L2300_1'
        WHEN '5' THEN 'L2300_2'
        WHEN '6' THEN 'L2300_3'
        WHEN '7' THEN 'L700'
        WHEN '8' THEN CASE WHEN LENGTH(cell::text) = 3 THEN 'L2600_3' ELSE 'L2600_1' END
        WHEN '9' THEN 'L2600_2'
        ELSE 'Unknown'
    END
"""
tech_case = f"""
    CASE
        WHEN {band_mapping} IN %s THEN 'FDD'
        WHEN {band_mapping} IN %s THEN 'TDD'
        ELSE 'Unknown'
    END
"""
kpi_selects = 'COALESCE(SUM("Traffic DL (GB)"), 0) AS payloadChart'

query = f"""
    SELECT
        CASE WHEN GROUPING(datehour) = 1 THEN TO_CHAR(date, 'YYYY-MM-DD') ELSE TO_CHAR(datehour, 'YYYY-MM-DD HH24:MI') END AS dt_label,
        CASE WHEN GROUPING(datehour) = 1 THEN 'daily' ELSE 'hourly' END AS gran,
        date,
        datehour,
        {tech_case} AS tech,
        {kpi_selects}
    FROM "4g_kpi_zte"
    WHERE date BETWEEN %s AND %s AND siteid IN %s
    GROUP BY GROUPING SETS (
        (date, {tech_case}),
        (date, datehour, {tech_case})
    )
    ORDER BY gran, date, datehour NULLS FIRST
"""

fdd_tup = ('L700', 'L900', 'L1800', 'L2100')
tdd_tup = ('L2600_1', 'L2600_2', 'L2600_3')

# Param order as in the CURRENT code: [fdd, tdd, fdd, tdd, fdd, tdd, from, to] + where
current_order = [fdd_tup, tdd_tup, fdd_tup, tdd_tup, fdd_tup, tdd_tup,
                 '2026-10-01', '2026-10-04', ('ZZZ_NO_SUCH_SITE',)]

print("=== CURRENT param order test ===")
try:
    cur.execute(query, current_order)
    rows = cur.fetchall()
    print(f"OK?! rows={len(rows)}")
except Exception as e:
    conn.rollback()
    print(f"FAILED: {type(e).__name__}: {e}")

# Correct textual order: SELECT tech_case(2), WHERE dates(2), where_entity(1), GS1(2), GS2(2)
correct_order = [fdd_tup, tdd_tup, '2026-10-01', '2026-10-04', ('ZZZ_NO_SUCH_SITE',),
                 fdd_tup, tdd_tup, fdd_tup, tdd_tup]
print("\n=== CORRECTED param order test ===")
try:
    t0 = time.perf_counter()
    cur.execute(query, correct_order)
    rows = cur.fetchall()
    t1 = time.perf_counter()
    print(f"OK rows={len(rows)} time={1000*(t1-t0):.0f} ms")
    for r in rows[:5]:
        print(r)
except Exception as e:
    conn.rollback()
    print(f"FAILED: {type(e).__name__}: {e}")

# Realistic test with an actual site + different band selections
print("\n=== REALISTIC test: real site, TDD-only vs all bands ===")
cur.execute("""SELECT siteid FROM "4g_kpi_zte" WHERE date = '2026-10-03' LIMIT 1""")
site = cur.fetchone()[0]
print("site:", site)

def run(fdd, tdd, label):
    params = [tuple(fdd), tuple(tdd), '2026-10-01', '2026-10-04', (site,),
              tuple(fdd), tuple(tdd), tuple(fdd), tuple(tdd)]
    t0 = time.perf_counter()
    cur.execute(query, params)
    rows = cur.fetchall()
    t1 = time.perf_counter()
    daily = {r[4]: r[5] for r in rows if r[1] == 'daily'}
    print(f"{label}: rows={len(rows)} time={1000*(t1-t0):.0f}ms daily={daily}")

run(['L700', 'L900', 'L1800', 'L2100'], ['L2300_1', 'L2300_2', 'L2300_3'], "FDD4+TDD2300")
run(['L700', 'L900', 'L1800', 'L2100'], ['L2600_1', 'L2600_2', 'L2600_3'], "FDD4+TDD2600")
run([], ['L2600_1', 'L2600_2', 'L2600_3'], "TDD2600 only")

conn.close()