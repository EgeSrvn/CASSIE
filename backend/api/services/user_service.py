"""
User service for database operations.

This module provides database operations for user management.
"""

from datetime import datetime
from typing import Optional
from backend.api.database.db_init import get_db_connection
from backend.api.models.user_model import UserInDB, UserCreate, UserProfileUpdate, UserResponse
from backend.api.services.auth_service import hash_password
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

USER_SELECT_COLUMNS = """
    id, username, email, password_hash, bucket_name, email_verified,
    display_name, bio, affiliation, job_title, location, website_url, avatar_url, login_two_factor_enabled, job_notifications_enabled,
    email_verification_code, email_verification_expires_at,
    password_reset_code, password_reset_expires_at,
    login_two_factor_code, login_two_factor_expires_at,
    suspended_until, suspension_reason,
    created_at, updated_at
"""


def purge_expired_unverified_users() -> int:
    """Delete accounts that were never verified before their verification window expired."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                DELETE FROM users
                WHERE email_verified = FALSE
                  AND email_verification_expires_at IS NOT NULL
                  AND email_verification_expires_at < NOW()
                """
            )
            deleted_count = cur.rowcount
            conn.commit()
            return deleted_count
        except Exception as e:
            conn.rollback()
            logger.error(f"Error purging expired unverified users: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def _row_to_user(row) -> UserInDB:
    return UserInDB(
        id=row[0],
        username=row[1],
        email=row[2],
        password_hash=row[3],
        bucket_name=row[4],
        email_verified=row[5],
        display_name=row[6],
        bio=row[7],
        affiliation=row[8],
        job_title=row[9],
        location=row[10],
        website_url=row[11],
        avatar_url=row[12],
        login_two_factor_enabled=bool(row[13]),
        job_notifications_enabled=bool(row[14]),
        email_verification_code=row[15],
        email_verification_expires_at=row[16],
        password_reset_code=row[17],
        password_reset_expires_at=row[18],
        login_two_factor_code=row[19],
        login_two_factor_expires_at=row[20],
        suspended_until=row[21],
        suspension_reason=row[22],
        created_at=row[23],
        updated_at=row[24]
    )


def create_user(user_data: UserCreate, email_verified: bool = False) -> UserInDB:
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
            purge_expired_unverified_users()

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
            cur.execute(f"""
                INSERT INTO users (username, email, password_hash, bucket_name, email_verified)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {USER_SELECT_COLUMNS}
            """, (
                user_data.username,
                user_data.email,
                password_hash,
                user_data.bucket_name,
                email_verified,
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
            cur.execute(f"""
                SELECT
                    {USER_SELECT_COLUMNS}
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
            cur.execute(f"""
                SELECT
                    {USER_SELECT_COLUMNS}
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
            cur.execute(f"""
                SELECT
                    {USER_SELECT_COLUMNS}
                FROM users
                WHERE email = %s
            """, (email,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            return _row_to_user(row)
        finally:
            cur.close()


def delete_user_account(user_id: int) -> bool:
    """Delete a user account and cascade-linked records."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute("DELETE FROM users WHERE id = %s", (user_id,))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting user account: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def set_account_deletion_code(user_id: int, code: str, expires_at: datetime) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                UPDATE users
                SET account_deletion_code = %s,
                    account_deletion_expires_at = %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (code, expires_at, user_id),
            )
            updated = cur.rowcount > 0
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            logger.error(f"Error setting account deletion code: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_account_deletion_code_state(user_id: int) -> tuple[Optional[str], Optional[datetime]]:
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                SELECT account_deletion_code, account_deletion_expires_at
                FROM users
                WHERE id = %s
                """,
                (user_id,),
            )
            row = cur.fetchone()
            if not row:
                return None, None
            return row[0], row[1]
        finally:
            cur.close()


def clear_account_deletion_code(user_id: int) -> bool:
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            cur.execute(
                """
                UPDATE users
                SET account_deletion_code = NULL,
                    account_deletion_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (user_id,),
            )
            updated = cur.rowcount > 0
            conn.commit()
            return updated
        except Exception as e:
            conn.rollback()
            logger.error(f"Error clearing account deletion code: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def update_user_password(user_id: int, new_password: str) -> Optional[UserInDB]:
    """Update a user's password hash and return the refreshed user record."""
    with get_db_connection() as conn:
        cur = conn.cursor()

        try:
            password_hash = hash_password(new_password)
            cur.execute(
                f"""
                UPDATE users
                SET password_hash = %s, updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
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
                "login_two_factor_enabled": profile_update.login_two_factor_enabled,
                "job_notifications_enabled": profile_update.job_notifications_enabled,
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
                RETURNING {USER_SELECT_COLUMNS}
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
                f"""
                INSERT INTO users (username, email, password_hash, bucket_name, email_verified)
                VALUES (%s, %s, %s, %s, %s)
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (
                    config.admin_panel.username,
                    admin_email,
                    password_hash,
                    f"cassie-user-{config.admin_panel.username}",
                    True,
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


def set_email_verification_code(user_id: int, code: str, expires_at: datetime) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET email_verification_code = %s,
                    email_verification_expires_at = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (code, expires_at, user_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error setting email verification code: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def verify_user_email(user_id: int) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET email_verified = TRUE,
                    email_verification_code = NULL,
                    email_verification_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (user_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error verifying user email: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def set_password_reset_code(user_id: int, code: str, expires_at: datetime) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET password_reset_code = %s,
                    password_reset_expires_at = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (code, expires_at, user_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error setting password reset code: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def set_login_two_factor_code(user_id: int, code: str, expires_at: datetime) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET login_two_factor_code = %s,
                    login_two_factor_expires_at = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (code, expires_at, user_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error setting login two-factor code: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def clear_login_two_factor_code(user_id: int) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET login_two_factor_code = NULL,
                    login_two_factor_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (user_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error clearing login two-factor code: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def reset_email_security_preferences(user_id: int, new_email: str) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET email = %s,
                    email_verified = FALSE,
                    email_verification_code = NULL,
                    email_verification_expires_at = NULL,
                    login_two_factor_enabled = FALSE,
                    job_notifications_enabled = FALSE,
                    login_two_factor_code = NULL,
                    login_two_factor_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (new_email, user_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error resetting email security preferences: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def clear_password_reset_code(user_id: int) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET password_reset_code = NULL,
                    password_reset_expires_at = NULL,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (user_id,),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error clearing password reset code: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def set_user_suspension(user_id: int, suspended_until: Optional[datetime], reason: Optional[str] = None) -> Optional[UserInDB]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                f"""
                UPDATE users
                SET suspended_until = %s,
                    suspension_reason = %s,
                    updated_at = NOW()
                WHERE id = %s
                RETURNING {USER_SELECT_COLUMNS}
                """,
                (suspended_until, reason, user_id),
            )
            row = cur.fetchone()
            conn.commit()
            return _row_to_user(row) if row else None
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating user suspension: {e}", exc_info=True)
            raise
        finally:
            cur.close()
