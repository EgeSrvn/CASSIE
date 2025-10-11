import docker
import time
import psycopg2

def ensure_postgres_container():
    """Ensure the PostgreSQL container is running or create it."""
    client = docker.from_env()
    container_name = "postgres-db"
    try:
        container = client.containers.get(container_name)
        if container.status != "running":
            print("[*] Starting existing PostgreSQL container...")
            container.start()
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
        time.sleep(6)  # Give it a few seconds to initialize

def get_connection():
    """Return a PostgreSQL connection."""
    ensure_postgres_container()
    return psycopg2.connect(
        host="localhost",
        port=5432,
        user="admin",
        password="admin",
        dbname="cloud_system"
    )

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
