"""
User service for database operations.

This module provides database operations for user management.
"""

import json
from typing import Optional
from contextlib import contextmanager
from backend.api.database.db_init import get_db_connection
from backend.api.models.user_model import UserInDB, UserCreate, UserResponse
from backend.api.utils.logger import get_logger
from backend.api.services.auth_service import hash_password

logger = get_logger(__name__)


def create_user(user_data: UserCreate) -> UserInDB:
    """
    Create a new user in the database.
    
    Args:
        user_data: User creation data
        
    Returns:
        UserInDB: Created user with database fields
        
    Raises:
        ValueError: If username or email already exists
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Check if username already exists
            cur.execute("SELECT id FROM users WHERE username = %s", (user_data.username,))
            if cur.fetchone():
                raise ValueError(f"Username '{user_data.username}' already exists")
            
            # Check if email already exists (if provided)
            if user_data.email:
                cur.execute("SELECT id FROM users WHERE email = %s", (user_data.email,))
                if cur.fetchone():
                    raise ValueError(f"Email '{user_data.email}' already exists")
            
            # Hash password
            password_hash = hash_password(user_data.password)
            
            # Insert user
            cur.execute("""
                INSERT INTO users (username, email, password_hash, bucket_name)
                VALUES (%s, %s, %s, %s)
                RETURNING id, username, email, password_hash, bucket_name, created_at, updated_at
            """, (
                user_data.username,
                user_data.email,
                password_hash,
                user_data.bucket_name
            ))
            
            row = cur.fetchone()
            conn.commit()
            
            return UserInDB(
                id=row[0],
                username=row[1],
                email=row[2],
                password_hash=row[3],
                bucket_name=row[4],
                created_at=row[5],
                updated_at=row[6]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating user: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_user_by_username(username: str) -> Optional[UserInDB]:
    """
    Get a user by username.
    
    Args:
        username: Username to search for
        
    Returns:
        UserInDB: User if found, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, username, email, password_hash, bucket_name, created_at, updated_at
                FROM users
                WHERE username = %s
            """, (username,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return UserInDB(
                id=row[0],
                username=row[1],
                email=row[2],
                password_hash=row[3],
                bucket_name=row[4],
                created_at=row[5],
                updated_at=row[6]
            )
        finally:
            cur.close()


def get_user_by_id(user_id: int) -> Optional[UserInDB]:
    """
    Get a user by ID.
    
    Args:
        user_id: User ID to search for
        
    Returns:
        UserInDB: User if found, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, username, email, password_hash, bucket_name, created_at, updated_at
                FROM users
                WHERE id = %s
            """, (user_id,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return UserInDB(
                id=row[0],
                username=row[1],
                email=row[2],
                password_hash=row[3],
                bucket_name=row[4],
                created_at=row[5],
                updated_at=row[6]
            )
        finally:
            cur.close()


def get_user_by_email(email: str) -> Optional[UserInDB]:
    """
    Get a user by email.
    
    Args:
        email: Email to search for
        
    Returns:
        UserInDB: User if found, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, username, email, password_hash, bucket_name, created_at, updated_at
                FROM users
                WHERE email = %s
            """, (email,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return UserInDB(
                id=row[0],
                username=row[1],
                email=row[2],
                password_hash=row[3],
                bucket_name=row[4],
                created_at=row[5],
                updated_at=row[6]
            )
        finally:
            cur.close()

