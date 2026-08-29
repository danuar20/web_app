"""
Migration script to add column 'Provider' to table 'sites_db' and backfill existing rows with 'Telkomsel'.

Usage:
    python -m scripts.migrate_add_provider
"""

import psycopg2
from app.db.db_webapp import get_postgres_connection

TABLE_NAME = "sites_db"

def run_migration():
    print(f"Connecting to PostgreSQL database to update table '{TABLE_NAME}'...")
    conn = get_postgres_connection()
    cur = conn.cursor()

    try:
        # Check if table exists
        cur.execute("""
            SELECT EXISTS (
                SELECT FROM information_schema.tables 
                WHERE table_name = %s
            )
        """, (TABLE_NAME,))
        table_exists = cur.fetchone()[0]

        if not table_exists:
            print(f"Table '{TABLE_NAME}' does not exist yet. Creating table...")
            cur.execute(f"""
                CREATE TABLE IF NOT EXISTS "{TABLE_NAME}" (
                    "SiteID"      VARCHAR(50),
                    "SiteID_v2"   VARCHAR(50),
                    "tac"         INTEGER,
                    "longitude"   DOUBLE PRECISION,
                    "latitude"    DOUBLE PRECISION,
                    "NOP"         VARCHAR(100),
                    "RTPO"        VARCHAR(100),
                    "kabupaten"   VARCHAR(100),
                    "Provider"    VARCHAR(100) DEFAULT 'Telkomsel'
                )
            """)
            conn.commit()
            print(f"Table '{TABLE_NAME}' created with 'Provider' column.")
            return

        # Check if 'Provider' column exists (case-insensitive check in information_schema)
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND LOWER(column_name) = 'provider'
        """, (TABLE_NAME,))
        existing_col = cur.fetchone()

        if not existing_col:
            print(f"Adding column 'Provider' to '{TABLE_NAME}'...")
            cur.execute(f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN "Provider" VARCHAR(100) DEFAULT \'Telkomsel\';')
            conn.commit()
            print("Column 'Provider' added.")
        else:
            print(f"Column '{existing_col[0]}' already exists in '{TABLE_NAME}'.")

        # Backfill existing rows where Provider is NULL or empty
        print("Backfilling NULL or empty Provider values with 'Telkomsel'...")
        cur.execute(f'UPDATE "{TABLE_NAME}" SET "Provider" = \'Telkomsel\' WHERE "Provider" IS NULL OR TRIM("Provider") = \'\';')
        updated_rows = cur.rowcount
        conn.commit()
        print(f"Backfill complete! Updated {updated_rows} rows.")

        # Verify count
        cur.execute(f'SELECT "Provider", COUNT(*) FROM "{TABLE_NAME}" GROUP BY "Provider"')
        summary = cur.fetchall()
        print("Current Provider distribution in database:")
        for prov, count in summary:
            print(f"  - {prov}: {count} records")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_migration()
