import docker
import time
import psycopg2
from psycopg2 import OperationalError

def ensure_postgres_container():
    """Ensure the PostgreSQL container is running or create it, and wait until it's accepting connections."""
    client = docker.from_env()
    container_name = "postgres-db"
    started = False
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            print("[*] Starting existing PostgreSQL container...")
            container.start()
            started = True
        else:
            print("[*] PostgreSQL container already running.")
    except docker.errors.NotFound:
        print("[*] Creating new PostgreSQL container...")
        client.containers.run(
            "postgres:15",
            name=container_name,
            detach=True,
            environment={
                "POSTGRES_USER": "admin",
                "POSTGRES_PASSWORD": "admin",
                "POSTGRES_DB": "cloud_system"
            },
            ports={"5432/tcp": 5432},
            volumes={"postgres_data": {"bind": "/var/lib/postgresql/data", "mode": "rw"}}
        )
        print("[+] PostgreSQL container started.")
        started = True

    # Wait until Postgres accepts connections (timeout 60s)
    deadline = time.time() + 60
    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host="localhost",
                port=5432,
                user="admin",
                password="admin",
                dbname="cloud_system",
                connect_timeout=3
            )
            conn.close()
            # ready
            return
        except OperationalError:
            time.sleep(1)
            continue

    # If we reach here, Postgres never became ready
    raise RuntimeError("PostgreSQL did not become ready within timeout. Check container logs.")

def get_connection():
    """Return a PostgreSQL connection (ensures Postgres container is running and ready)."""
    # Ensure container exists & is running and ready to accept connections
    ensure_postgres_container()

    # Try to connect, raise if still failing after retries
    deadline = time.time() + 30
    last_exc = None
    while time.time() < deadline:
        try:
            return psycopg2.connect(
                host="localhost",
                port=5432,
                user="admin",
                password="admin",
                dbname="cloud_system",
                connect_timeout=5
            )
        except OperationalError as e:
            last_exc = e
            time.sleep(1)

    raise RuntimeError(f"Unable to connect to PostgreSQL: {last_exc}")

def initialize_database():
    """Initialize or migrate database schema for multi-tenant user system."""
    conn = get_connection()
    cur = conn.cursor()

    # Users table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            username VARCHAR(50) UNIQUE NOT NULL,
            bucket_name VARCHAR(100) UNIQUE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # VMs table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS vms (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) UNIQUE NOT NULL,
            max_capacity INTEGER NOT NULL,
            current_load INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    # Tenants table
    cur.execute("""
        CREATE TABLE IF NOT EXISTS tenants (
            id SERIAL PRIMARY KEY,
            name VARCHAR(50) NOT NULL,
            vm_name VARCHAR(50),
            user_id INTEGER REFERENCES users(id) ON DELETE CASCADE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    conn.commit()
    cur.close()
    conn.close()
    print("[+] Database initialized successfully.")
