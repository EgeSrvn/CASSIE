"""
Database connection and initialization module for CASSIE backend.

This module provides:
- PostgreSQL connection management with connection pooling
- Database creation (if it doesn't exist)
- Database schema initialization
- Schema verification and health checks
- Context manager for safe connection handling

Based on Project Analysis PDF requirements and updated schema with 11 tables:
- users, workflows, pipeline_configs, jobs, job_executions, files
- datasets, community_workflows, saved_workflows, votes, execution_datasets
"""

import os
import sys
import time
import psycopg2
from psycopg2 import pool, OperationalError, Error
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from contextlib import contextmanager
from typing import Optional, List, Tuple

# Try to import docker for container management (optional)
try:
    import docker
    DOCKER_AVAILABLE = True
except ImportError:
    DOCKER_AVAILABLE = False

# Connection pool (will be initialized on first use)
_connection_pool: Optional[pool.SimpleConnectionPool] = None

# Expected tables in the database (based on updated schema)
EXPECTED_TABLES = [
    'users',
    'workflows',
    'pipeline_configs',
    'pipelines',  # User-created visual pipelines
    'pipeline_votes',
    'forum_threads',
    'forum_answers',
    'forum_comments',
    'forum_thread_votes',
    'forum_comment_votes',
    'moderation_reports',
    'folders',  # User-managed folder structure
    'jobs',
    'job_executions',
    'files',
    'datasets',
    'community_workflows',
    'saved_workflows',
    'votes',
    'execution_datasets',
    'invitation_codes',
    'vms',  # Emulation-only (temporary)
    'tenants'  # Emulation-only (temporary)
]


def get_db_config():
    """
    Get database connection configuration from environment variables.
    Returns defaults suitable for local prototyping if not set.
    
    Returns:
        dict: Database connection parameters
    """
    password = os.getenv("DB_PASSWORD", "admin")
    environment = os.getenv("CASSIE_ENV", os.getenv("ENVIRONMENT", "development")).lower()
    allow_insecure = os.getenv("CASSIE_ALLOW_INSECURE_DEFAULTS", "false").lower() in {"1", "true", "yes"}
    if password in {"", "admin", "password"} and environment in {"prod", "production"} and not allow_insecure:
        raise RuntimeError("DB_PASSWORD must be set to a strong value in production.")

    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "5433")),
        "user": os.getenv("DB_USER", "admin"),
        "password": password,
        "database": os.getenv("DB_NAME", "cassie_db")
    }


def get_db_config_no_database():
    """
    Get database connection configuration without specifying a database.
    Used for creating the database if it doesn't exist.
    
    Returns:
        dict: Database connection parameters (without database name)
    """
    config = get_db_config()
    config["database"] = "postgres"  # Connect to default postgres database
    return config


def ensure_postgres_container():
    """
    Ensure PostgreSQL Docker container is running.
    
    This function checks if the PostgreSQL container exists and is running.
    If not, it creates/starts it. This is useful for local development.
    
    Returns:
        bool: True if container is running or was started, False otherwise
    """
    if not DOCKER_AVAILABLE:
        # Docker not available, assume PostgreSQL is running externally
        return True
    
    try:
        client = docker.from_env()
        config = get_db_config()
        container_name = "postgres-cassie"
        
        try:
            container = client.containers.get(container_name)
            if container.status == "running":
                return True
            else:
                print(f"[*] Starting existing PostgreSQL container '{container_name}'...")
                container.start()
                time.sleep(2)
                return True
        except docker.errors.NotFound:
            print(f"[*] Creating new PostgreSQL container '{container_name}'...")
            client.containers.run(
                "postgres:15",
                name=container_name,
                detach=True,
                environment={
                    "POSTGRES_USER": config["user"],
                    "POSTGRES_PASSWORD": config["password"],
                    "POSTGRES_DB": "postgres"  # Default database
                },
                ports={"5432/tcp": config["port"]},
                volumes={"postgres_cassie_data": {"bind": "/var/lib/postgresql/data", "mode": "rw"}}
            )
            print("[+] Container created. Waiting for PostgreSQL to be ready...")
            time.sleep(3)
            return True
    except Exception as e:
        print(f"[!] Warning: Could not ensure PostgreSQL container: {e}")
        print("[*] Assuming PostgreSQL is running externally or will be started manually.")
        return False


def wait_for_postgres(max_wait=60):
    """
    Wait for PostgreSQL to accept connections.
    
    Args:
        max_wait: Maximum time to wait in seconds (default: 60)
    
    Returns:
        bool: True if PostgreSQL is ready, False otherwise
    """
    config = get_db_config()
    deadline = time.time() + max_wait
    last_err = None
    
    print(f"[*] Waiting for PostgreSQL on {config['host']}:{config['port']}...")
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host=config["host"],
                port=config["port"],
                user=config["user"],
                password=config["password"],
                dbname="postgres",
                connect_timeout=3
            )
            conn.close()
            print("[+] PostgreSQL is ready!")
            return True
        except OperationalError as e:
            last_err = e
            time.sleep(1)
    
    if last_err:
        print(f"[!] PostgreSQL did not become ready: {last_err}")
    return False


def get_connection(retries: int = 3, delay: float = 1.0):
    """
    Get a database connection from the connection pool.
    Creates the pool if it doesn't exist.
    Includes retry logic for transient connection failures.
    
    Args:
        retries: Number of retry attempts (default: 3)
        delay: Delay between retries in seconds (default: 1.0)
    
    Returns:
        psycopg2.connection: Database connection
    
    Raises:
        RuntimeError: If connection cannot be established after retries
    """
    global _connection_pool
    
    if _connection_pool is None:
        config = get_db_config()
        last_error = None
        
        for attempt in range(retries):
            try:
                _connection_pool = pool.SimpleConnectionPool(
                    minconn=1,
                    maxconn=10,
                    host=config["host"],
                    port=config["port"],
                    user=config["user"],
                    password=config["password"],
                    database=config["database"]
                )
                break  # Success, exit retry loop
            except OperationalError as e:
                last_error = e
                if attempt < retries - 1:
                    print(f"[*] Connection attempt {attempt + 1} failed, retrying in {delay}s...")
                    time.sleep(delay)
                else:
                    raise RuntimeError(
                        f"Failed to create database connection pool after {retries} attempts: {last_error}\n"
                        f"Please ensure PostgreSQL is running and accessible at {config['host']}:{config['port']}"
                    )
    
    # Get connection from pool with retries
    last_error = None
    for attempt in range(retries):
        try:
            return _connection_pool.getconn()
        except Exception as e:
            last_error = e
            if attempt < retries - 1:
                print(f"[*] Failed to get connection from pool (attempt {attempt + 1}), retrying...")
                time.sleep(delay)
            else:
                raise RuntimeError(f"Failed to get connection from pool after {retries} attempts: {last_error}")


def return_connection(conn):
    """
    Return a connection to the pool.
    
    Args:
        conn: Database connection to return
    """
    global _connection_pool
    if _connection_pool and conn:
        _connection_pool.putconn(conn)


@contextmanager
def get_db_connection():
    """
    Context manager for database connections.
    Automatically returns connection to pool when done.
    
    Usage:
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT * FROM users")
            results = cur.fetchall()
            cur.close()
    
    Yields:
        psycopg2.connection: Database connection
    """
    conn = None
    try:
        conn = get_connection()
        yield conn
    finally:
        if conn:
            return_connection(conn)


def database_exists() -> bool:
    """
    Check if the target database exists.
    
    Returns:
        bool: True if database exists, False otherwise
    """
    config = get_db_config()
    no_db_config = get_db_config_no_database()
    
    try:
        conn = psycopg2.connect(
            host=no_db_config["host"],
            port=no_db_config["port"],
            user=no_db_config["user"],
            password=no_db_config["password"],
            database=no_db_config["database"],
            connect_timeout=5
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        cur.execute(
            "SELECT 1 FROM pg_database WHERE datname = %s",
            (config["database"],)
        )
        exists = cur.fetchone() is not None
        
        cur.close()
        conn.close()
        return exists
    except Exception as e:
        print(f"[!] Error checking if database exists: {e}")
        return False


def create_database_if_not_exists():
    """
    Create the database if it doesn't exist.
    This function connects to the default 'postgres' database to create the target database.
    
    Returns:
        bool: True if database was created or already exists, False on error
    """
    config = get_db_config()
    no_db_config = get_db_config_no_database()
    
    if database_exists():
        print(f"[+] Database '{config['database']}' already exists.")
        return True
    
    print(f"[*] Creating database '{config['database']}'...")
    
    try:
        conn = psycopg2.connect(
            host=no_db_config["host"],
            port=no_db_config["port"],
            user=no_db_config["user"],
            password=no_db_config["password"],
            database=no_db_config["database"],
            connect_timeout=5
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        
        cur.execute(f'CREATE DATABASE {config["database"]}')
        print(f"[+] Database '{config['database']}' created successfully.")
        
        cur.close()
        conn.close()
        
        # Wait a moment for database to be fully ready
        time.sleep(0.5)
        return True
    except Exception as e:
        print(f"[!] Error creating database: {e}")
        return False


def verify_schema() -> Tuple[bool, List[str], List[str]]:
    """
    Verify that all expected tables exist in the database.
    
    Returns:
        Tuple[bool, List[str], List[str]]: 
            - True if all tables exist, False otherwise
            - List of missing tables
            - List of existing tables
    """
    try:
        with get_db_connection() as conn:
            cur = conn.cursor()
            
            # Get all tables in public schema
            cur.execute("""
                SELECT table_name 
                FROM information_schema.tables 
                WHERE table_schema = 'public'
                ORDER BY table_name;
            """)
            existing_tables = [row[0] for row in cur.fetchall()]
            
            missing_tables = [t for t in EXPECTED_TABLES if t not in existing_tables]
            all_present = len(missing_tables) == 0
            
            cur.close()
            return all_present, missing_tables, existing_tables
    except Exception as e:
        print(f"[!] Error verifying schema: {e}")
        return False, EXPECTED_TABLES, []


def initialize_database(create_db: bool = True, verify: bool = True):
    """
    Initialize the database schema by executing the SQL schema file.
    This function is idempotent and can be safely called multiple times.
    
    Args:
        create_db: If True, create the database if it doesn't exist (default: True)
        verify: If True, verify schema after initialization (default: True)
    
    Raises:
        FileNotFoundError: If schema file is not found
        RuntimeError: If database initialization fails
    """
    # Step 0: Ensure PostgreSQL container is running (for local development)
    ensure_postgres_container()
    if not wait_for_postgres(max_wait=60):
        raise RuntimeError(
            "PostgreSQL is not available. Please ensure PostgreSQL is running.\n"
            "For local development, the container should start automatically.\n"
            "If using external PostgreSQL, ensure it's accessible."
        )
    
    # Step 1: Create database if needed
    if create_db:
        if not create_database_if_not_exists():
            raise RuntimeError("Failed to create database. Please check PostgreSQL connection.")
    
    # Step 2: Load and execute schema
    current_dir = os.path.dirname(os.path.abspath(__file__))
    schema_file = os.path.join(current_dir, "schemas.sql")

    if not os.path.exists(schema_file):
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    print(f"[*] Loading schema from {schema_file}...")
    with open(schema_file, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    print("[*] Executing schema SQL...")
    with get_db_connection() as conn:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        try:
            # Execute entire schema in one go — Postgres handles $$ blocks correctly
            cur.execute(schema_sql)
            print("[+] Database schema SQL executed successfully.")
        except Error as e:
            error_msg = f"Error initializing database schema: {e}"
            print(f"[!] {error_msg}")
            raise RuntimeError(error_msg) from e
        finally:
            cur.close()
    
    # Step 3: Verify schema
    if verify:
        print("[*] Verifying schema...")
        all_present, missing, existing = verify_schema()
        
        if all_present:
            print(f"[+] Schema verification passed. All {len(EXPECTED_TABLES)} tables exist.")
        else:
            print(f"[!] Schema verification failed. Missing tables: {', '.join(missing)}")
            print(f"[*] Existing tables: {', '.join(existing)}")
            raise RuntimeError(f"Schema verification failed. Missing tables: {', '.join(missing)}")


def check_database_health() -> dict:
    """
    Perform a basic health check on the database connection and schema.
    
    Returns:
        dict: Dictionary with 'healthy' (bool) and optional 'error' (str) keys
    """
    try:
        # Test connection
        with get_db_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT version();")
            version = cur.fetchone()[0]
            cur.close()
        
        # Verify schema
        all_present, missing, _ = verify_schema()
        
        if all_present:
            print(f"[+] Database health check passed. PostgreSQL version: {version.split(',')[0]}")
            return {"healthy": True}
        else:
            error_msg = f"Missing tables: {', '.join(missing)}"
            print(f"[!] Database health check failed. {error_msg}")
            return {"healthy": False, "error": error_msg}
    except Exception as e:
        error_msg = str(e)
        print(f"[!] Database health check failed: {error_msg}")
        return {"healthy": False, "error": error_msg}




def close_pool():
    """
    Close all connections in the connection pool.
    Should be called during application shutdown.
    """
    global _connection_pool
    if _connection_pool:
        _connection_pool.closeall()
        _connection_pool = None
        print("[+] Database connection pool closed.")


def reset_connection_pool():
    """
    Reset the connection pool (close and clear).
    Useful for reconnecting after database configuration changes.
    """
    close_pool()
    print("[+] Connection pool reset. New connections will use updated configuration.")


def main():
    """
    Main function for running database initialization as a script.
    
    Usage:
        python -m backend.api.database.db_init
    """
    print("=" * 60)
    print("CASSIE Database Initialization")
    print("=" * 60)
    print()
    
    config = get_db_config()
    print(f"Configuration:")
    print(f"  Host: {config['host']}")
    print(f"  Port: {config['port']}")
    print(f"  User: {config['user']}")
    print(f"  Database: {config['database']}")
    print()
    
    try:
        # Initialize database (creates DB if needed, runs schema, verifies)
        initialize_database(create_db=True, verify=True)
        
        print()
        print("=" * 60)
        print("✅ Database initialization completed successfully!")
        print("=" * 60)
        
        # Run health check
        print()
        if check_database_health():
            print()
            print("✅ Database is ready to use.")
            return True
        else:
            print()
            print("⚠️  Database initialized but health check failed.")
            return False
            
    except Exception as e:
        print()
        print("=" * 60)
        print("❌ Database initialization failed!")
        print("=" * 60)
        print(f"Error: {e}")
        print()
        print("Troubleshooting:")
        print("  1. Ensure PostgreSQL is running")
        print("  2. Check connection settings (DB_HOST, DB_PORT, etc.)")
        print("  3. Verify database credentials")
        print("  4. Check that schemas.sql file exists")
        return False
    finally:
        close_pool()


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
