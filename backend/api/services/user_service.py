"""
User service for database operations.

This module provides database operations for user management.
"""

import json
from typing import Optional
from contextlib import contextmanager
from backend.api.database.db_init import get_db_connection
from backend.api.models.user_model import UserInDB, UserCreate, UserProfileUpdate, UserResponse
from backend.api.services.auth_service import hash_password
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def _row_to_user(row) -> UserInDB:
    return UserInDB(
        id=row[0],
        username=row[1],
        email=row[2],
        password_hash=row[3],
        bucket_name=row[4],
        display_name=row[5],
        bio=row[6],
        affiliation=row[7],
        job_title=row[8],
        location=row[9],
        website_url=row[10],
        avatar_url=row[11],
        created_at=row[12],
        updated_at=row[13]
    )


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
                RETURNING
                    id, username, email, password_hash, bucket_name,
                    display_name, bio, affiliation, job_title, location, website_url, avatar_url,
                    created_at, updated_at
            """, (
                user_data.username,
                user_data.email,
                password_hash,
                user_data.bucket_name
            ))
            
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row)
            
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
                SELECT
                    id, username, email, password_hash, bucket_name,
                    display_name, bio, affiliation, job_title, location, website_url, avatar_url,
                    created_at, updated_at
                FROM users
                WHERE username = %s
            """, (username,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return _row_to_user(row)
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
                SELECT
                    id, username, email, password_hash, bucket_name,
                    display_name, bio, affiliation, job_title, location, website_url, avatar_url,
                    created_at, updated_at
                FROM users
                WHERE id = %s
            """, (user_id,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return _row_to_user(row)
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
                SELECT
                    id, username, email, password_hash, bucket_name,
                    display_name, bio, affiliation, job_title, location, website_url, avatar_url,
                    created_at, updated_at
                FROM users
                WHERE email = %s
            """, (email,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return _row_to_user(row)
        finally:
            cur.close()


def update_user_password(user_id: int, new_password: str) -> Optional[UserInDB]:
    """Update a user's password hash and return the refreshed user record."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            password_hash = hash_password(new_password)
            cur.execute(
                """
                UPDATE users
                SET password_hash = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING
                    id, username, email, password_hash, bucket_name,
                    display_name, bio, affiliation, job_title, location, website_url, avatar_url,
                    created_at, updated_at
                """,
                (password_hash, user_id),
            )
            row = cur.fetchone()
            conn.commit()

            if not row:
                return None

            return _row_to_user(row)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating user password: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def update_user_profile(user_id: int, profile_update: UserProfileUpdate) -> Optional[UserInDB]:
    """Update editable profile fields for a user."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            updates = []
            params = []
            field_map = {
                "email": profile_update.email,
                "display_name": profile_update.display_name,
                "bio": profile_update.bio,
                "affiliation": profile_update.affiliation,
                "job_title": profile_update.job_title,
                "location": profile_update.location,
                "website_url": profile_update.website_url,
                "avatar_url": profile_update.avatar_url,
            }
            for column, value in field_map.items():
                if value is not None:
                    updates.append(f"{column} = %s")
                    params.append(value)

            if not updates:
                return get_user_by_id(user_id)

            updates.append("updated_at = NOW()")
            params.append(user_id)

            cur.execute(
                f"""
                UPDATE users
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING
                    id, username, email, password_hash, bucket_name,
                    display_name, bio, affiliation, job_title, location, website_url, avatar_url,
                    created_at, updated_at
                """,
                params,
            )
            row = cur.fetchone()
            conn.commit()
            if not row:
                return None
            return _row_to_user(row)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating user profile: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def ensure_admin_user() -> UserInDB:
    """
    Ensure the admin-panel user exists.

    The initial password is only applied when the admin account is first created.
    Subsequent restarts preserve any password changed from the admin panel.
    """
    config = get_config()
    existing = get_user_by_username(config.admin_panel.username)
    if existing:
        return existing

    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            password_hash = hash_password(config.admin_panel.default_password)
            admin_email = f"{config.admin_panel.username}@local.admin"
            cur.execute(
                """
                INSERT INTO users (username, email, password_hash, bucket_name)
                VALUES (%s, %s, %s, %s)
                RETURNING
                    id, username, email, password_hash, bucket_name,
                    display_name, bio, affiliation, job_title, location, website_url, avatar_url,
                    created_at, updated_at
                """,
                (
                    config.admin_panel.username,
                    admin_email,
                    password_hash,
                    f"cassie-user-{config.admin_panel.username}",
                ),
            )
            row = cur.fetchone()
            conn.commit()

            return _row_to_user(row)
        except Exception as e:
            conn.rollback()
            logger.error(f"Error ensuring admin user: {e}", exc_info=True)
            raise
        finally:
            cur.close()
