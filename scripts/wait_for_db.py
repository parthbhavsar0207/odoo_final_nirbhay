"""
Helper script to verify PostgreSQL database connectivity before running migrations.
"""

import os
import sys
import time

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

def check_db():
    db_name = os.getenv('DB_NAME', 'champions_club')
    db_user = os.getenv('DB_USER', 'postgres')
    db_password = os.getenv('DB_PASSWORD', 'postgres')
    db_host = os.getenv('DB_HOST', '127.0.0.1')
    db_port = os.getenv('DB_PORT', '5433')

    try:
        import psycopg
        conn = psycopg.connect(
            dbname=db_name,
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port,
            connect_timeout=3
        )
        conn.close()
        print(f"Successfully connected to PostgreSQL at {db_host}:{db_port}/{db_name}")
        return True
    except ImportError:
        print("Note: psycopg is not installed yet. Install requirements first.")
        return False
    except Exception as exc:
        print(f"Waiting for database ({db_host}:{db_port})... {exc}")
        return False

if __name__ == '__main__':
    max_retries = 10
    retry_interval = 2

    for attempt in range(1, max_retries + 1):
        if check_db():
            sys.exit(0)
        time.sleep(retry_interval)

    print("PostgreSQL connection check timed out.")
    sys.exit(1)
