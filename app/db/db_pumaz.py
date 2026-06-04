import psycopg2
import os
import time

def _connect_with_retry(connect_fn, max_retries=2, delay=1.0):
    for attempt in range(max_retries):
        try:
            return connect_fn()
        except psycopg2.OperationalError:
            if attempt == max_retries - 1:
                raise
            time.sleep(delay * (attempt + 1))
    raise psycopg2.OperationalError("Max retries exceeded")

def get_pumaz_connection():
    """Connect to Pumaz database for traffic and payload data"""
    def _conn():
        return psycopg2.connect(
            host=os.getenv("PUMAZ_DB_HOST"),
            database=os.getenv("PUMAZ_DB_NAME"),
            user=os.getenv("PUMAZ_DB_USER"),
            password=os.getenv("PUMAZ_DB_PASSWORD"),
            port=os.getenv("PUMAZ_DB_PORT", "5432"),
            connect_timeout=12,
            options="-c statement_timeout=360000"
        )
    return _connect_with_retry(_conn)