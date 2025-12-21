import os
import time
import psycopg2
from psycopg2 import OperationalError

def get_db_config():
    """
    Get database connection configuration.
    Uses the same settings as the backend (from environment variables or defaults).

    Returns:
        dict: Database connection parameters
    """
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "5433")),  # Backend uses 5433 by default
        "user": os.getenv("DB_USER", "admin"),
        "password": os.getenv("DB_PASSWORD", "admin"),
        "database": os.getenv("DB_NAME", "cassie_db")  # Backend uses cassie_db
    }

def get_connection():
    """Obtain a psycopg2 connection to the PostgreSQL database.

    This function connects to the database managed by the backend.
    It does NOT create or manage containers - that's handled by the backend.
    It will retry until a 30 second deadline before failing.

    Returns:
        psycopg2.connection: An open database connection to the backend's database.

    Raises:
        RuntimeError: If a connection could not be established within the retry period.
    """
    config = get_db_config()

    # Try to connect, raise if still failing after retries
    deadline = time.time() + 30
    last_exc = None
    while time.time() < deadline:
        try:
            return psycopg2.connect(
                host=config["host"],
                port=config["port"],
                user=config["user"],
                password=config["password"],
                dbname=config["database"],
                connect_timeout=5
            )
        except OperationalError as e:
            last_exc = e
            time.sleep(1)

    raise RuntimeError(
        f"Unable to connect to PostgreSQL at {config['host']}:{config['port']}. "
        f"Ensure the backend's PostgreSQL container (postgres-cassie) is running. "
        f"Error: {last_exc}"
    )

