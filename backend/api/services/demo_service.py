"""
Demo mode service for CASSIE backend.

Handles demo code generation, validation, session management, and cleanup.
Demo codes are one-time-use cryptographically random tokens stored as bcrypt hashes.
"""

import os
import secrets
import shutil
import string
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from backend.api.database.db_init import get_db_connection
from backend.api.services.auth_service import hash_password, verify_password
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

# Characters used for demo codes: uppercase letters + digits, excluding ambiguous chars O/0/I/1
_CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"


def _generate_plaintext_code(length: int) -> str:
    """Generate a cryptographically random demo code from the unambiguous alphabet."""
    return "".join(secrets.choice(_CODE_ALPHABET) for _ in range(length))


def generate_demo_codes(
    admin_user_id: int,
    count: int = 1,
    expires_at: Optional[datetime] = None,
) -> list[str]:
    """
    Generate one-time demo codes and store their hashes in the database.

    Returns plaintext codes — this is the ONLY time they are available.
    The database stores only bcrypt hashes.
    """
    config = get_config()
    code_length = config.demo.code_length
    plaintext_codes = []

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            for _ in range(count):
                plaintext = _generate_plaintext_code(code_length)
                code_hash = hash_password(plaintext)
                masked = plaintext[:4] + "*" * (code_length - 4)

                cur.execute(
                    """
                    INSERT INTO demo_codes
                        (code_hash, code_prefix_masked, created_by_admin_id, expires_at)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (code_hash, masked, admin_user_id, expires_at),
                )
                plaintext_codes.append(plaintext)

            conn.commit()
            logger.info(
                "Demo codes generated",
                extra={"count": count, "admin_user_id": admin_user_id},
            )
        except Exception as e:
            conn.rollback()
            logger.error("Error generating demo codes: %s", e, exc_info=True)
            raise
        finally:
            cur.close()

    return plaintext_codes


def validate_and_consume_demo_code(plaintext_code: str) -> dict:
    """
    Validate a plaintext demo code against stored hashes.

    On success, marks the code as used and creates a demo_sessions row.
    Returns a dict with session_id and demo_code_id.
    Raises ValueError with a generic message on any failure.
    """
    normalized = plaintext_code.strip().upper()
    config = get_config()

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            # Fetch all active, non-expired, unused codes for bcrypt comparison
            cur.execute(
                """
                SELECT id, code_hash
                FROM demo_codes
                WHERE is_active = TRUE
                  AND used_at IS NULL
                  AND deactivated_at IS NULL
                  AND (expires_at IS NULL OR expires_at > NOW())
                """
            )
            rows = cur.fetchall()

            matched_id = None
            for row_id, stored_hash in rows:
                if verify_password(normalized, stored_hash):
                    matched_id = row_id
                    break

            if matched_id is None:
                raise ValueError("Invalid or expired demo code.")

            session_id = str(uuid4())
            ttl_minutes = config.demo.session_ttl_minutes
            expires_at = datetime.now(timezone.utc) + timedelta(minutes=ttl_minutes)

            # Mark code as used atomically
            cur.execute(
                """
                UPDATE demo_codes
                SET used_at = NOW(), used_by_session_id = %s
                WHERE id = %s AND used_at IS NULL
                RETURNING id
                """,
                (session_id, matched_id),
            )
            if cur.rowcount == 0:
                # Race condition — code was consumed between our SELECT and UPDATE
                raise ValueError("Invalid or expired demo code.")

            # Create demo session record
            cur.execute(
                """
                INSERT INTO demo_sessions (id, demo_code_id, expires_at)
                VALUES (%s, %s, %s)
                """,
                (session_id, matched_id, expires_at),
            )

            conn.commit()
            logger.info("Demo session created", extra={"session_id": session_id})
            return {"session_id": session_id, "demo_code_id": matched_id, "expires_at": expires_at}

        except ValueError:
            conn.rollback()
            raise
        except Exception as e:
            conn.rollback()
            logger.error("Error validating demo code: %s", e, exc_info=True)
            raise ValueError("Invalid or expired demo code.")
        finally:
            cur.close()


def get_demo_codes() -> list[dict]:
    """List all demo codes with metadata. Never returns code_hash."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, code_prefix_masked, created_by_admin_id,
                       created_at, expires_at, used_at, used_by_session_id,
                       deactivated_at, is_active
                FROM demo_codes
                ORDER BY created_at DESC
                """
            )
            rows = cur.fetchall()
            result = []
            for row in rows:
                (
                    code_id, masked, admin_id, created_at, expires_at,
                    used_at, session_id, deactivated_at, is_active,
                ) = row

                if used_at:
                    status = "used"
                elif deactivated_at or not is_active:
                    status = "deactivated"
                elif expires_at and expires_at < datetime.now(timezone.utc):
                    status = "expired"
                else:
                    status = "active"

                result.append({
                    "id": code_id,
                    "masked_code": masked,
                    "status": status,
                    "created_by_admin_id": admin_id,
                    "created_at": created_at.isoformat() if created_at else None,
                    "expires_at": expires_at.isoformat() if expires_at else None,
                    "used_at": used_at.isoformat() if used_at else None,
                    "used_by_session_id": session_id,
                    "deactivated_at": deactivated_at.isoformat() if deactivated_at else None,
                    "is_active": bool(is_active),
                })
            return result
        finally:
            cur.close()


def deactivate_demo_code(code_id: int) -> bool:
    """Deactivate a demo code so it can no longer be used."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE demo_codes
                SET is_active = FALSE, deactivated_at = NOW()
                WHERE id = %s AND used_at IS NULL AND deactivated_at IS NULL
                RETURNING id
                """,
                (code_id,),
            )
            success = cur.rowcount > 0
            conn.commit()
            if success:
                logger.info("Demo code deactivated", extra={"code_id": code_id})
            return success
        except Exception as e:
            conn.rollback()
            logger.error("Error deactivating demo code: %s", e, exc_info=True)
            raise
        finally:
            cur.close()


def end_demo_session(session_id: str) -> bool:
    """Mark a demo session as ended (logout or expiry)."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE demo_sessions SET ended_at = NOW()
                WHERE id = %s AND ended_at IS NULL
                RETURNING id
                """,
                (session_id,),
            )
            success = cur.rowcount > 0
            conn.commit()
            return success
        except Exception as e:
            conn.rollback()
            logger.error("Error ending demo session: %s", e, exc_info=True)
            raise
        finally:
            cur.close()


def cleanup_expired_demo_sessions() -> int:
    """
    Delete output directories for expired/ended demo sessions and mark them cleaned.

    Only deletes paths strictly under DEMO_OUTPUT_ROOT — never arbitrary paths.
    """
    config = get_config()
    output_root = os.path.abspath(config.demo.output_root)
    cleaned_count = 0

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id FROM demo_sessions
                WHERE cleanup_completed_at IS NULL
                  AND (expires_at < NOW() OR ended_at IS NOT NULL)
                """
            )
            rows = cur.fetchall()

            for (session_id,) in rows:
                session_dir = os.path.join(output_root, session_id)
                abs_session_dir = os.path.abspath(session_dir)

                # Safety: only delete if path is under the output root
                if abs_session_dir.startswith(output_root + os.sep) or abs_session_dir == output_root:
                    if os.path.isdir(abs_session_dir):
                        try:
                            shutil.rmtree(abs_session_dir)
                            logger.info("Cleaned demo session output dir", extra={"session_id": session_id})
                        except Exception as rm_err:
                            logger.warning(
                                "Could not remove demo session dir: %s", rm_err,
                                extra={"session_id": session_id},
                            )

                cur.execute(
                    "UPDATE demo_sessions SET cleanup_completed_at = NOW() WHERE id = %s",
                    (session_id,),
                )
                cleaned_count += 1

            conn.commit()
            logger.info("Demo session cleanup completed", extra={"cleaned": cleaned_count})
            return cleaned_count
        except Exception as e:
            conn.rollback()
            logger.error("Error during demo session cleanup: %s", e, exc_info=True)
            raise
        finally:
            cur.close()
