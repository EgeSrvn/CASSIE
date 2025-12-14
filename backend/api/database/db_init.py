"""
Database connection and initialization module for CASSIE backend.

This module provides:
- PostgreSQL connection management
- Database schema initialization
- Context manager for safe connection handling
"""

import os
import re
import psycopg2
from psycopg2 import pool, OperationalError
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from contextlib import contextmanager
from typing import Optional

# Connection pool (will be initialized on first use)
_connection_pool: Optional[pool.SimpleConnectionPool] = None


def get_db_config():
    """
    Get database connection configuration from environment variables.
    Returns defaults suitable for local prototyping if not set.
    
    Returns:
        dict: Database connection parameters
    """
    return {
        "host": os.getenv("DB_HOST", "127.0.0.1"),
        "port": int(os.getenv("DB_PORT", "5433")),
        "user": os.getenv("DB_USER", "admin"),
        "password": os.getenv("DB_PASSWORD", "admin"),
        "database": os.getenv("DB_NAME", "cassie_db")
    }


def get_connection():
    """
    Get a database connection from the connection pool.
    Creates the pool if it doesn't exist.
    
    Returns:
        psycopg2.connection: Database connection
    
    Raises:
        RuntimeError: If connection cannot be established
    """
    global _connection_pool
    
    if _connection_pool is None:
        config = get_db_config()
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
        except OperationalError as e:
            raise RuntimeError(f"Failed to create database connection pool: {e}")
    
    try:
        return _connection_pool.getconn()
    except Exception as e:
        raise RuntimeError(f"Failed to get connection from pool: {e}")


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


def initialize_database():
    """
    Initialize the database schema by executing the SQL schema file.
    This function is idempotent and can be safely called multiple times.
    """
    current_dir = os.path.dirname(os.path.abspath(__file__))
    schema_file = os.path.join(current_dir, "schemas.sql")

    if not os.path.exists(schema_file):
        raise FileNotFoundError(f"Schema file not found: {schema_file}")

    with open(schema_file, "r", encoding="utf-8") as f:
        schema_sql = f.read()

    with get_db_connection() as conn:
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()
        try:
            # Execute entire schema in one go — Postgres handles $$ blocks correctly
            cur.execute(schema_sql)
            print("[+] Database schema initialized successfully.")
        except Exception as e:
            print(f"[!] Error initializing database schema: {e}")
            raise
        finally:
            cur.close()




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
