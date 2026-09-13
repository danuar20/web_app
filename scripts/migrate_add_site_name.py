"""
Migration script to add column 'site_name' to table 'sites_db'.

Usage:
    python -m scripts.migrate_add_site_name
"""

from app.db.db_webapp import get_postgres_connection

TABLE_NAME = "sites_db"

def run_migration():
    print(f"Connecting to PostgreSQL database to check/add 'site_name' in '{TABLE_NAME}'...")
    conn = get_postgres_connection()
    cur = conn.cursor()

    try:
        # Check if 'site_name' column exists
        cur.execute("""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = %s AND LOWER(column_name) = 'site_name'
        """, (TABLE_NAME,))
        existing_col = cur.fetchone()

        if not existing_col:
            print(f"Adding column 'site_name' to '{TABLE_NAME}'...")
            cur.execute(f'ALTER TABLE "{TABLE_NAME}" ADD COLUMN "site_name" VARCHAR(150);')
            conn.commit()
            print("Column 'site_name' added successfully.")
        else:
            print(f"Column '{existing_col[0]}' already exists in '{TABLE_NAME}'.")

        # Verify columns
        cur.execute("""
            SELECT column_name, data_type, character_maximum_length 
            FROM information_schema.columns 
            WHERE table_name = %s 
            ORDER BY ordinal_position
        """, (TABLE_NAME,))
        cols = cur.fetchall()
        print(f"Current columns in '{TABLE_NAME}':")
        for c in cols:
            print(f"  - {c[0]} ({c[1]}, max_len={c[2]})")

    except Exception as e:
        conn.rollback()
        print(f"Error during migration: {e}")
        raise
    finally:
        cur.close()
        conn.close()

if __name__ == "__main__":
    run_migration()
