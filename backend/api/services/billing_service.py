"""Cash balance reservation and job settlement helpers."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from typing import Optional

from backend.api.database.db_init import get_db_connection
from backend.api.services.runtime_estimator_service import get_vm_price_per_minute
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

CENT = Decimal("0.01")


def _money(value) -> Decimal:
    try:
        amount = Decimal(str(value or 0))
    except Exception:
        amount = Decimal("0")
    if amount < 0:
        amount = Decimal("0")
    return amount.quantize(CENT, rounding=ROUND_HALF_UP)


def _calculate_actual_charge(
    *,
    vm_name: Optional[str],
    started_at: Optional[datetime],
    completed_at: Optional[datetime],
    max_charge_usd: Decimal,
) -> Decimal:
    if max_charge_usd <= 0 or not started_at:
        return Decimal("0.00")

    if completed_at is not None:
        end_time = completed_at
    elif started_at.tzinfo is not None:
        end_time = datetime.now(tz=started_at.tzinfo)
    else:
        end_time = datetime.now()
    elapsed_seconds = max((end_time - started_at).total_seconds(), 0)
    elapsed_minutes = Decimal(str(elapsed_seconds / 60.0))
    price_per_minute = _money(get_vm_price_per_minute(vm_name))
    return min(_money(elapsed_minutes * price_per_minute), max_charge_usd)


def deposit_user_cash(user_id: int, amount_usd) -> None:
    amount = _money(amount_usd)
    if amount <= 0:
        raise ValueError("Deposit amount must be greater than 0.")
    if amount > Decimal("1000000.00"):
        raise ValueError("Deposit amount is too large.")

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                UPDATE users
                SET cash_balance_usd = cash_balance_usd + %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (amount, user_id),
            )
            if cur.rowcount == 0:
                raise ValueError("User not found.")
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def reserve_job_charge(job_id: int, user_id: int, estimated_price_usd) -> Decimal:
    estimate = _money(estimated_price_usd)
    max_charge = _money(estimate * Decimal("1.5"))

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT cash_balance_usd, cash_reserved_usd
                FROM users
                WHERE id = %s
                FOR UPDATE
                """,
                (user_id,),
            )
            user_row = cur.fetchone()
            if not user_row:
                raise ValueError("User not found.")

            balance = _money(user_row[0])
            reserved = _money(user_row[1])
            available = balance - reserved
            if available < max_charge:
                raise ValueError(
                    f"Insufficient balance. Required hold: ${max_charge:.2f}; available balance: ${available:.2f}."
                )

            cur.execute(
                """
                SELECT balance_reserved_at, max_charge_usd
                FROM jobs
                WHERE id = %s AND user_id = %s
                FOR UPDATE
                """,
                (job_id, user_id),
            )
            job_row = cur.fetchone()
            if not job_row:
                raise ValueError("Job not found.")

            if job_row[0] is not None:
                conn.commit()
                return _money(job_row[1])

            cur.execute(
                """
                UPDATE users
                SET cash_reserved_usd = cash_reserved_usd + %s,
                    updated_at = NOW()
                WHERE id = %s
                """,
                (max_charge, user_id),
            )
            cur.execute(
                """
                UPDATE jobs
                SET estimated_price_usd = %s,
                    max_charge_usd = %s,
                    balance_reserved_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (estimate, max_charge, job_id, user_id),
            )
            conn.commit()
            return max_charge
        except Exception:
            conn.rollback()
            raise
        finally:
            cur.close()


def settle_job_charge(job_id: int, user_id: int, execution_id: Optional[int] = None) -> Decimal:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id, vm_name, max_charge_usd, balance_reserved_at, balance_charged_at
                FROM jobs
                WHERE id = %s AND user_id = %s
                FOR UPDATE
                """,
                (job_id, user_id),
            )
            job_row = cur.fetchone()
            if not job_row:
                return Decimal("0.00")

            if job_row[4] is not None:
                return Decimal("0.00")

            max_charge = _money(job_row[2])
            if max_charge <= 0:
                cur.execute(
                    """
                    UPDATE jobs
                    SET actual_price_charged_usd = 0,
                        balance_charged_at = NOW(),
                        updated_at = NOW()
                    WHERE id = %s AND user_id = %s
                    """,
                    (job_id, user_id),
                )
                conn.commit()
                return Decimal("0.00")

            if execution_id is not None:
                cur.execute(
                    """
                    SELECT started_at, completed_at
                    FROM job_executions
                    WHERE id = %s AND job_id = %s
                    """,
                    (execution_id, job_id),
                )
            else:
                cur.execute(
                    """
                    SELECT started_at, completed_at
                    FROM job_executions
                    WHERE job_id = %s
                    ORDER BY created_at DESC
                    LIMIT 1
                    """,
                    (job_id,),
                )
            execution_row = cur.fetchone()
            started_at = execution_row[0] if execution_row else None
            completed_at = execution_row[1] if execution_row else None
            charge = _calculate_actual_charge(
                vm_name=job_row[1],
                started_at=started_at,
                completed_at=completed_at,
                max_charge_usd=max_charge,
            )

            cur.execute(
                """
                UPDATE users
                SET cash_reserved_usd = GREATEST(cash_reserved_usd - %s, 0),
                    cash_balance_usd = GREATEST(cash_balance_usd - %s, 0),
                    updated_at = NOW()
                WHERE id = %s
                """,
                (max_charge, charge, user_id),
            )
            cur.execute(
                """
                UPDATE jobs
                SET actual_price_charged_usd = %s,
                    balance_charged_at = NOW(),
                    updated_at = NOW()
                WHERE id = %s AND user_id = %s
                """,
                (charge, job_id, user_id),
            )
            conn.commit()
            return charge
        except Exception as exc:
            conn.rollback()
            logger.error(f"Failed to settle billing for job {job_id}: {exc}", exc_info=True)
            raise
        finally:
            cur.close()
