"""
Import site_list_4G_puma.csv into the 'sites_db' table in the postgres database.

Usage:
    python -m scripts.import_sites_db
"""

import csv
import psycopg2
from app.db.db_webapp import get_postgres_connection


CSV_PATH = r"E:\Server\files\site_list_4G_puma.csv"
TABLE_NAME = "sites_db"


def create_table(cur):
    cur.execute(f"""
        CREATE TABLE IF NOT EXISTS "{TABLE_NAME}" (
            "SiteID"      VARCHAR(50),
            "SiteID_v2"   VARCHAR(50),
            "tac"         INTEGER,
            "longitude"   DOUBLE PRECISION,
            "latitude"    DOUBLE PRECISION,
            "NOP"         VARCHAR(100),
            "RTPO"        VARCHAR(100),
            "kabupaten"   VARCHAR(100)
        )
    """)


def import_csv(cur, filepath):
    with open(filepath, "r", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        rows = []
        for row in reader:
            rows.append((
                row["SiteID"].strip() if row["SiteID"] else None,
                row["SiteID_v2"].strip() if row["SiteID_v2"] else None,
                int(row["tac"]) if row["tac"] else None,
                float(row["longitude"]) if row["longitude"] else None,
                float(row["latitude"]) if row["latitude"] else None,
                row["NOP"].strip() if row["NOP"] else None,
                row["RTPO"].strip() if row["RTPO"] else None,
                row["kabupaten"].strip() if row["kabupaten"] else None,
            ))

    insert_sql = f"""
        INSERT INTO "{TABLE_NAME}" ("SiteID", "SiteID_v2", "tac", "longitude", "latitude", "NOP", "RTPO", "kabupaten")
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
    """
    cur.executemany(insert_sql, rows)
    return len(rows)


def main():
    conn = get_postgres_connection()
    cur = conn.cursor()

    try:
        # Drop existing table to do a full refresh
        cur.execute(f'DROP TABLE IF EXISTS "{TABLE_NAME}"')
        print(f"Dropped existing '{TABLE_NAME}' table (if any).")

        create_table(cur)
        print(f"Created table '{TABLE_NAME}'.")

        count = import_csv(cur, CSV_PATH)
        conn.commit()
        print(f"Successfully imported {count} rows into '{TABLE_NAME}'.")
    except Exception as e:
        conn.rollback()
        print(f"Error: {e}")
        raise
    finally:
        cur.close()
        conn.close()


if __name__ == "__main__":
    main()
