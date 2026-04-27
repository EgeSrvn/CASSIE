"""
User-specific runtime limits for job execution and output access.
"""

from typing import Optional, Set

from backend.api.database.db_init import get_db_connection
from backend.api.models.job_model import ExecutionStatus, JobStatus
from backend.api.models.pipeline_model import FileType
from backend.api.services.storage_service import get_total_file_bytes_by_user
from backend.api.utils.config_loader import get_config


TERMINAL_JOB_STATUSES = {
    JobStatus.COMPLETED.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
}

ACTIVE_EXECUTION_QUEUE_STATES = {
    "reserved_for_upload",
}


def get_user_limits(username: Optional[str]) -> dict:
    return get_config().user_limits.get_limits_for_username(username)


def get_recent_finished_job_ids_for_user(user_id: int, username: Optional[str], limit_key: str) -> Set[int]:
    limits = get_user_limits(username)
    max_finished_jobs = max(int(limits.get(limit_key, 0)), 0)
    if max_finished_jobs == 0:
        return set()

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT id
                FROM jobs
                WHERE user_id = %s
                  AND status = ANY(%s)
                ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                LIMIT %s
                """,
                (user_id, list(TERMINAL_JOB_STATUSES), max_finished_jobs),
            )
            return {int(row[0]) for row in cur.fetchall()}
        finally:
            cur.close()


def count_running_jobs_for_user(user_id: int) -> int:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT COUNT(DISTINCT e.job_id)
                FROM job_executions e
                JOIN jobs j ON j.id = e.job_id
                WHERE j.user_id = %s
                  AND (
                        e.status = %s
                        OR (
                            e.status = %s
                            AND COALESCE(e.parameters_used->>'queue_state', '') = ANY(%s)
                        )
                  )
                  AND j.status = ANY(%s)
                """,
                (
                    user_id,
                    ExecutionStatus.RUNNING.value,
                    ExecutionStatus.PENDING.value,
                    list(ACTIVE_EXECUTION_QUEUE_STATES),
                    [JobStatus.PENDING.value, JobStatus.RUNNING.value],
                ),
            )
            return int(cur.fetchone()[0] or 0)
        finally:
            cur.close()


def get_downloadable_finished_job_ids_for_user(user_id: int, username: Optional[str]) -> Set[int]:
    return get_recent_finished_job_ids_for_user(user_id, username, "downloadable_finished_jobs")


def get_job_status_for_user(user_id: int, job_id: Optional[int]) -> Optional[str]:
    if job_id is None:
        return None

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT status
                FROM jobs
                WHERE id = %s
                  AND user_id = %s
                """,
                (job_id, user_id),
            )
            row = cur.fetchone()
            return str(row[0]) if row and row[0] is not None else None
        finally:
            cur.close()


def can_user_start_more_jobs(user_id: int, username: Optional[str]) -> tuple[bool, int, int]:
    limits = get_user_limits(username)
    max_running_jobs = max(int(limits.get("max_running_jobs", 0)), 0)
    current_running_jobs = count_running_jobs_for_user(user_id)

    if max_running_jobs <= 0:
        return True, current_running_jobs, max_running_jobs

    return current_running_jobs < max_running_jobs, current_running_jobs, max_running_jobs


def validate_user_storage_capacity(
    user_id: int,
    username: Optional[str],
    incoming_bytes: int,
    available_bytes: Optional[int] = None,
) -> tuple[bool, str]:
    limits = get_user_limits(username)
    max_storage_bytes = max(int(limits.get("max_storage_bytes", 0)), 0)
    min_free_storage_bytes = max(int(limits.get("min_free_storage_bytes", 0)), 0)

    if available_bytes is not None and min_free_storage_bytes > 0:
        if available_bytes - incoming_bytes < min_free_storage_bytes:
            return (
                False,
                "Upload refused because the storage backend is almost full. "
                "Delete old Docker/MinIO data or increase MIN_FREE_STORAGE_GB before uploading more files.",
            )

    if max_storage_bytes <= 0:
        return True, ""

    current_bytes = get_total_file_bytes_by_user(user_id)
    if current_bytes + incoming_bytes <= max_storage_bytes:
        return True, ""

    limit_gb = max_storage_bytes / (1024 * 1024 * 1024)
    used_gb = current_bytes / (1024 * 1024 * 1024)
    incoming_gb = incoming_bytes / (1024 * 1024 * 1024)
    return (
        False,
        (
            f"Upload would exceed your storage quota of {limit_gb:.1f} GB "
            f"(currently used {used_gb:.1f} GB, incoming file {incoming_gb:.1f} GB)."
        ),
    )


def can_user_access_job_outputs(
    user_id: int,
    username: Optional[str],
    job_id: Optional[int],
    job_status: Optional[str] = None,
) -> tuple[bool, int]:
    if job_id is None:
        return False, 0

    resolved_status = job_status or get_job_status_for_user(user_id, job_id)
    if resolved_status not in TERMINAL_JOB_STATUSES:
        limits = get_user_limits(username)
        max_finished_jobs = max(int(limits.get("downloadable_finished_jobs", 0)), 0)
        return True, max_finished_jobs

    limits = get_user_limits(username)
    max_finished_jobs = max(int(limits.get("downloadable_finished_jobs", 0)), 0)
    allowed_job_ids = get_downloadable_finished_job_ids_for_user(user_id, username)
    return job_id in allowed_job_ids, max_finished_jobs


def can_user_interact_with_job_outputs(
    user_id: int,
    username: Optional[str],
    job_id: Optional[int],
    job_status: Optional[str] = None,
) -> tuple[bool, int]:
    if job_id is None:
        return False, 0

    limits = get_user_limits(username)
    max_finished_jobs = max(int(limits.get("interactive_output_jobs", 0)), 0)

    if job_status not in TERMINAL_JOB_STATUSES:
        return True, max_finished_jobs

    allowed_job_ids = get_recent_finished_job_ids_for_user(user_id, username, "interactive_output_jobs")
    return job_id in allowed_job_ids, max_finished_jobs


def validate_output_file_access(file_record, user_id: int, username: Optional[str]) -> tuple[bool, Optional[str]]:
    if getattr(file_record, "file_type", None) != FileType.OUTPUT:
        return True, None

    job_status = get_job_status_for_user(user_id, getattr(file_record, "job_id", None))
    allowed, max_finished_jobs = can_user_access_job_outputs(
        user_id=user_id,
        username=username,
        job_id=getattr(file_record, "job_id", None),
        job_status=job_status,
    )
    if allowed:
        return True, None

    return (
        False,
        (
            f"Output downloads are limited to your latest {max_finished_jobs} finished jobs. "
            "This job is outside that window."
        ),
    )
