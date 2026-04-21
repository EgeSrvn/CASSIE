from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from backend.api.services.email_service import send_email
from backend.api.services.user_service import get_user_by_id
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def _normalize_datetime(value: Optional[datetime]) -> Optional[datetime]:
    if value is None:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def build_login_two_factor_email(username: str, code: str, expires_in_minutes: int) -> tuple[str, str, str]:
    subject = "Your CASSIE login code"
    text_body = (
        f"Hello {username},\n\n"
        f"Your CASSIE login code is: {code}\n"
        f"It expires in {expires_in_minutes} minutes.\n\n"
        "If you did not attempt to sign in, you can ignore this email."
    )
    html_body = (
        f"<p>Hello {username},</p>"
        "<p>Use this code to finish signing in to CASSIE:</p>"
        f"<p style=\"font-size:24px;font-weight:700;letter-spacing:4px;\">{code}</p>"
        f"<p>It expires in {expires_in_minutes} minutes.</p>"
        "<p>If you did not attempt to sign in, you can ignore this email.</p>"
    )
    return subject, text_body, html_body


def send_job_checkpoint_notification(
    user_id: int,
    *,
    job_id: int,
    job_name: str,
    checkpoint_name: str,
    stage_number: Optional[int] = None,
) -> bool:
    user = get_user_by_id(user_id)
    if user is None or not getattr(user, "job_notifications_enabled", False):
        return False
    if not getattr(user, "email_verified", False) or not getattr(user, "email", None):
        return False

    stage_label = f"Checkpoint {stage_number}" if stage_number is not None else "Checkpoint"
    subject = f"CASSIE checkpoint reached for job {job_name}"
    text_body = (
        f"Hello {user.username},\n\n"
        f"Your job \"{job_name}\" (ID {job_id}) is waiting at {stage_label}: {checkpoint_name}.\n"
        "Open the job details page to review the current state and resume execution when you are ready."
    )
    html_body = (
        f"<p>Hello {user.username},</p>"
        f"<p>Your job <strong>{job_name}</strong> (ID {job_id}) is waiting at "
        f"<strong>{stage_label}: {checkpoint_name}</strong>.</p>"
        "<p>Open the job details page to review the current state and resume execution when you are ready.</p>"
    )
    return send_email(user.email, subject, text_body, html_body)


def send_job_completed_notification(user_id: int, *, job_id: int, job_name: str) -> bool:
    user = get_user_by_id(user_id)
    if user is None or not getattr(user, "job_notifications_enabled", False):
        return False
    if not getattr(user, "email_verified", False) or not getattr(user, "email", None):
        return False

    subject = f"CASSIE job finished: {job_name}"
    text_body = (
        f"Hello {user.username},\n\n"
        f"Your job \"{job_name}\" (ID {job_id}) has finished successfully.\n"
        "You can open CASSIE to review outputs, logs, and downstream results."
    )
    html_body = (
        f"<p>Hello {user.username},</p>"
        f"<p>Your job <strong>{job_name}</strong> (ID {job_id}) has finished successfully.</p>"
        "<p>You can open CASSIE to review outputs, logs, and downstream results.</p>"
    )
    return send_email(user.email, subject, text_body, html_body)
