"""Temporary diagnostic: inspect band columns/data for L2600 migration planning."""
import os
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

print("=== unbalance_prb columns ===")
cur.execute("""SELECT column_name FROM information_schema.columns
               WHERE table_name='unbalance_prb' ORDER BY ordinal_position""")
print([r[0] for r in cur.fetchall()])

print("\n=== unbalance_prb_weekly columns ===")
cur.execute("""SELECT column_name FROM information_schema.columns
               WHERE table_name='unbalance_prb_weekly' ORDER BY ordinal_position""")
print([r[0] for r in cur.fetchall()])

print("\n=== distinct bands, week >= 2026-W36 ===")
cur.execute("""SELECT DISTINCT band FROM unbalance_prb
               WHERE week >= '2026-W36' ORDER BY band""")
print([r[0] for r in cur.fetchall()])

print("\n=== bands per week (W35..W39) ===")
cur.execute("""SELECT week, COUNT(DISTINCT band), string_agg(DISTINCT band, ', ' ORDER BY band)
               FROM unbalance_prb WHERE week >= '2026-W35'
               GROUP BY week ORDER BY week""")
for row in cur.fetchall():
    print(row)

print("\n=== weeks present in unbalance_prb_weekly ===")
cur.execute('SELECT week, COUNT(*) FROM unbalance_prb_weekly GROUP BY week ORDER BY week')
for row in cur.fetchall():
    print(row)

print("\n=== row counts ===")
cur.execute('SELECT COUNT(*) FROM unbalance_prb')
print("unbalance_prb rows:", cur.fetchone()[0])
cur.execute('SELECT COUNT(*) FROM unbalance_prb_weekly')
print("unbalance_prb_weekly rows:", cur.fetchone()[0])

conn.close()