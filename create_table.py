import psycopg2
from app.db.db_webapp import get_postgres_connection

def create_custom_charts_table():
    conn = get_postgres_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS user_custom_charts (
            id SERIAL PRIMARY KEY,
            username VARCHAR(255) NOT NULL,
            dashboard_name VARCHAR(255) NOT NULL,
            chart_config JSONB NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE (username, dashboard_name)
        )
    """)
    conn.commit()
    cur.close()
    conn.close()
    print("Table user_custom_charts created successfully.")

if __name__ == "__main__":
    create_custom_charts_table()
