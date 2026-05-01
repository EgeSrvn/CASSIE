"""Invitation-code operations for registration gating."""

from __future__ import annotations

import secrets
import string
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from backend.api.database.db_init import get_db_connection
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

INVITATION_CODE_ALPHABET = string.ascii_uppercase + string.digits


@dataclass(frozen=True)
class InvitationCode:
    id: int
    code: str
    note: Optional[str]
    created_by_user_id: Optional[int]
    used_by_user_id: Optional[int]
    used_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


def normalize_invitation_code(code: str) -> str:
    compact = "".join(char for char in str(code or "").upper() if char.isalnum())
    return "-".join(compact[index:index + 4] for index in range(0, len(compact), 4))


def _row_to_invitation_code(row) -> InvitationCode:
    return InvitationCode(
        id=row[0],
        code=row[1],
        note=row[2],
        created_by_user_id=row[3],
        used_by_user_id=row[4],
        used_at=row[5],
        created_at=row[6],
        updated_at=row[7],
    )


def _generate_code_value(length: int = 16) -> str:
    grouped = "".join(secrets.choice(INVITATION_CODE_ALPHABET) for _ in range(length))
    return "-".join(grouped[index:index + 4] for index in range(0, len(grouped), 4))


def create_invitation_code(*, created_by_user_id: Optional[int], note: Optional[str] = None) -> InvitationCode:
    """Create a unique one-use invitation code."""
    clean_note = str(note or "").strip()[:255] or None

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            for _ in range(10):
                code = _generate_code_value()
                try:
                    cur.execute(
                        """
                        INSERT INTO invitation_codes (code, note, created_by_user_id)
                        VALUES (%s, %s, %s)
                        RETURNING id, code, note, created_by_user_id, used_by_user_id, used_at, created_at, updated_at
                        """,
                        (code, clean_note, created_by_user_id),
                    )
                    row = cur.fetchone()
                    conn.commit()
                    return _row_to_invitation_code(row)
                except Exception:
                    conn.rollback()
                    logger.warning("Invitation code collision or insert failure; retrying", exc_info=True)
            raise RuntimeError("Could not generate a unique invitation code")
        finally:
            cur.close()


def list_invitation_codes(limit: int = 100) -> list[InvitationCode]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, code, note, created_by_user_id, used_by_user_id, used_at, created_at, updated_at
                FROM invitation_codes
                ORDER BY created_at DESC
                LIMIT %s
                """,
                (max(1, min(limit, 500)),),
            )
            return [_row_to_invitation_code(row) for row in cur.fetchall()]
        finally:
            cur.close()


def claim_invitation_code(code: str) -> InvitationCode:
    """Mark an invitation code as used. Raises ValueError if invalid or already used."""
    normalized = normalize_invitation_code(code)
    if not normalized:
        raise ValueError("Invitation code is required")

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE invitation_codes
                SET used_at = NOW(), updated_at = NOW()
                WHERE code = %s
                  AND used_at IS NULL
                  AND used_by_user_id IS NULL
                RETURNING id, code, note, created_by_user_id, used_by_user_id, used_at, created_at, updated_at
                """,
                (normalized,),
            )
            row = cur.fetchone()
            if not row:
                conn.rollback()
                raise ValueError("Invalid or already used invitation code")
            conn.commit()
            return _row_to_invitation_code(row)
        except ValueError:
            raise
        except Exception as exc:
            conn.rollback()
            logger.error("Error claiming invitation code: %s", exc, exc_info=True)
            raise
        finally:
            cur.close()


def attach_invitation_code_to_user(invitation_code_id: int, user_id: int) -> None:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE invitation_codes
                SET used_by_user_id = %s, updated_at = NOW()
                WHERE id = %s AND used_at IS NOT NULL
                """,
                (user_id, invitation_code_id),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def release_invitation_code(invitation_code_id: int) -> None:
    """Release a claimed code if registration failed before a user was attached."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE invitation_codes
                SET used_at = NULL, used_by_user_id = NULL, updated_at = NOW()
                WHERE id = %s AND used_by_user_id IS NULL
                """,
                (invitation_code_id,),
            )
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()
