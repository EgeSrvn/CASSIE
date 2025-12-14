"""
Helper script to set up PostgreSQL database for CASSIE.

This script:
1. Starts a PostgreSQL Docker container (if not running)
2. Creates the database if it doesn't exist
3. Optionally initializes the schema

Usage:
    python backend/scripts/setup_database.py
"""

import sys
import os
import time

# Add parent directory to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

try:
    import docker
    import psycopg2
    from psycopg2 import OperationalError
except ImportError as e:
    print(f"Error: Missing required package: {e}")
    print("Please install: pip install docker psycopg2-binary")
    sys.exit(1)
    
POSTGRES_HOST = "127.0.0.1"
POSTGRES_PORT = int(os.getenv("CASSIE_PG_PORT", "5433"))  # host port



def ensure_postgres_container():
    """Ensure PostgreSQL container is running."""
    print("[*] Checking PostgreSQL container...")
    
    client = docker.from_env()
    container_name = "postgres-cassie"
    
    try:
        container = client.containers.get(container_name)
        if container.status == "running":
            print(f"[+] Container '{container_name}' is already running.")
            return True
        else:
            print(f"[*] Starting existing container '{container_name}'...")
            container.start()
            time.sleep(2)
            return True
    except docker.errors.NotFound:
        print(f"[*] Creating new PostgreSQL container '{container_name}'...")
        try:
            client.containers.run(
                "postgres:15",
                name=container_name,
                detach=True,
                environment={
                    "POSTGRES_USER": "admin",
                    "POSTGRES_PASSWORD": "admin",
                    "POSTGRES_DB": "postgres"  # Default database
                },
                ports={"5432/tcp": POSTGRES_PORT},
                volumes={"postgres_cassie_data": {"bind": "/var/lib/postgresql/data", "mode": "rw"}}
            )
            print("[+] Container created. Waiting for PostgreSQL to be ready...")
            time.sleep(3)
            return True
        except Exception as e:
            print(f"[!] Failed to create container: {e}")
            return False
    except Exception as e:
        print(f"[!] Error checking container: {e}")
        return False


def wait_for_postgres(max_wait=90):
    """Wait for PostgreSQL to accept connections."""
    print(f"[*] Waiting for PostgreSQL on {POSTGRES_HOST}:{POSTGRES_PORT} ...")
    deadline = time.time() + max_wait
    last_err = None

    while time.time() < deadline:
        try:
            conn = psycopg2.connect(
                host=POSTGRES_HOST,
                port=POSTGRES_PORT,
                user="admin",
                password="admin",
                dbname="postgres",
                connect_timeout=3
            )
            conn.close()
            print("[+] PostgreSQL is ready!")
            return True
        except OperationalError as e:
            last_err = e
            # Print the first line so it doesn't spam
            print("[.] not ready yet:", str(e).splitlines()[0])
            time.sleep(2)

    print("[!] PostgreSQL did not become ready within timeout.")
    if last_err:
        print("[!] Last error was:", str(last_err).splitlines()[0])
    return False



def create_database():
    """Create the cassie_db database if it doesn't exist."""
    print("[*] Creating database 'cassie_db' if it doesn't exist...")
    
    try:
        # Connect to default postgres database
        conn = psycopg2.connect(
            host=POSTGRES_HOST,
            port=POSTGRES_PORT,
            user="admin",
            password="admin",
            dbname="postgres",
            connect_timeout=3
        )

        conn.autocommit = True
        cur = conn.cursor()
        
        # Check if database exists
        cur.execute("SELECT 1 FROM pg_database WHERE datname = 'cassie_db'")
        exists = cur.fetchone()
        
        if not exists:
            cur.execute('CREATE DATABASE cassie_db')
            print("[+] Database 'cassie_db' created.")
        else:
            print("[+] Database 'cassie_db' already exists.")
        
        cur.close()
        conn.close()
        return True
    except Exception as e:
        print(f"[!] Failed to create database: {e}")
        return False


def main():
    """Main setup function."""
    print("=" * 60)
    print("CASSIE Database Setup")
    print("=" * 60)
    
    # Step 1: Ensure container is running
    if not ensure_postgres_container():
        print("\n❌ Failed to start PostgreSQL container.")
        return False
    
    # Step 2: Wait for PostgreSQL to be ready
    if not wait_for_postgres():
        print("\n❌ PostgreSQL did not become ready.")
        return False
    
    # Step 3: Create database
    if not create_database():
        print("\n❌ Failed to create database.")
        return False
    
    print("\n" + "=" * 60)
    print("✅ Database setup complete!")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Run the test script: python -m backend.tests.test_database_setup")
    print("  2. Or initialize schema manually using db_init.initialize_database()")
    print("\nConnection details:")
    print(f"  Host: {POSTGRES_HOST}")
    print(f"  Port: {POSTGRES_PORT}")
    print("  User: admin")
    print("  Password: admin")
    print("  Database: cassie_db")
    
    return True


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
