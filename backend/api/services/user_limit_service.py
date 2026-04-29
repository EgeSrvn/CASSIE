"""
User-specific runtime limits for job execution, storage, and output access.
"""

import json
from pathlib import Path
from typing import Any, Dict, Optional, Set

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
GIB = 1024 * 1024 * 1024


def get_user_limits(username: Optional[str]) -> dict:
    return get_config().user_limits.get_limits_for_username(username)


def _user_limits_config_path() -> Path:
    return get_config().user_limits.path


def _storage_upgrade_catalog_path() -> Path:
    return Path(__file__).resolve().parents[3] / "storage_upgrade_plans.json"


def _load_json_file(path: Path, fallback: Dict[str, Any]) -> Dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            payload = json.load(handle)
            if isinstance(payload, dict):
                return payload
    except Exception:
        pass
    return dict(fallback)


def _write_user_limits_config(payload: Dict[str, Any]) -> None:
    path = _user_limits_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)
        handle.write("\n")
    get_config().user_limits.raw = payload


def get_storage_upgrade_catalog() -> Dict[str, Any]:
    return _load_json_file(
        _storage_upgrade_catalog_path(),
        {
            "currency": "USD",
            "billing_interval": "week",
            "plans": [],
        },
    )


def get_storage_upgrade_plan(plan_id: str) -> Optional[Dict[str, Any]]:
    normalized_plan_id = str(plan_id or "").strip()
    if not normalized_plan_id:
        return None

    for plan in get_storage_upgrade_catalog().get("plans", []):
        if not isinstance(plan, dict):
            continue
        if str(plan.get("id") or "").strip() == normalized_plan_id:
            return plan
    return None


def set_user_max_storage_gb(username: str, max_storage_gb: float) -> Dict[str, Any]:
    normalized_username = str(username or "").strip()
    if not normalized_username:
        raise ValueError("Username is required to update storage limits.")
    if max_storage_gb <= 0:
        raise ValueError("Storage quota must be greater than zero.")

    config_payload = _load_json_file(
        _user_limits_config_path(),
        {
            "default": {
                "max_running_jobs": get_config().user_limits.default_max_running_jobs,
                "downloadable_finished_jobs": get_config().user_limits.default_downloadable_finished_jobs,
                "interactive_output_jobs": get_config().user_limits.default_interactive_output_jobs,
                "max_storage_gb": get_config().user_limits.default_max_storage_gb,
                "min_free_storage_gb": get_config().user_limits.default_min_free_storage_gb,
            },
            "users": {},
        },
    )

    if not isinstance(config_payload.get("users"), dict):
        config_payload["users"] = {}

    user_overrides = config_payload["users"].get(normalized_username)
    if not isinstance(user_overrides, dict):
        user_overrides = {}
    user_overrides["max_storage_gb"] = round(float(max_storage_gb), 3)
    config_payload["users"][normalized_username] = user_overrides
    _write_user_limits_config(config_payload)
    return get_user_limits(normalized_username)


def increase_user_max_storage_gb(username: str, additional_gb: float) -> Dict[str, Any]:
    if additional_gb <= 0:
        raise ValueError("Additional storage must be greater than zero.")
    current_limits = get_user_limits(username)
    current_max_storage_gb = max(float(current_limits.get("max_storage_bytes", 0)) / GIB, 0.0)
    return set_user_max_storage_gb(username, current_max_storage_gb + float(additional_gb))


def get_user_storage_usage(user_id: int, username: Optional[str]) -> Dict[str, float]:
    limits = get_user_limits(username)
    max_storage_bytes = max(int(limits.get("max_storage_bytes", 0)), 0)
    used_bytes = get_total_file_bytes_by_user(user_id)
    return {
        "used_bytes": used_bytes,
        "max_storage_bytes": max_storage_bytes,
        "remaining_bytes": max(max_storage_bytes - used_bytes, 0) if max_storage_bytes > 0 else 0,
        "used_gb": used_bytes / GIB,
        "max_storage_gb": max_storage_bytes / GIB if max_storage_bytes > 0 else 0.0,
    }


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


def validate_user_storage_headroom(
    user_id: int,
    username: Optional[str],
    required_bytes: int = 1,
    *,
    action_label: str = "This action",
) -> tuple[bool, str]:
    current_usage = get_user_storage_usage(user_id, username)
    max_storage_bytes = int(current_usage["max_storage_bytes"])
    used_bytes = int(current_usage["used_bytes"])

    if max_storage_bytes <= 0:
        return True, ""

    normalized_required_bytes = max(int(required_bytes or 0), 0)
    if used_bytes + normalized_required_bytes <= max_storage_bytes:
        return True, ""

    used_gb = current_usage["used_gb"]
    max_storage_gb = current_usage["max_storage_gb"]
    required_gb = normalized_required_bytes / GIB
    if normalized_required_bytes <= 1:
        return (
            False,
            (
                f"{action_label} is blocked because your storage quota is full "
                f"({used_gb:.1f} GB used out of {max_storage_gb:.1f} GB). "
                "Delete input or output files, or purchase more storage, before starting another job."
            ),
        )

    return (
        False,
        (
            f"{action_label} would exceed your storage quota of {max_storage_gb:.1f} GB "
            f"(currently used {used_gb:.1f} GB, this step needs {required_gb:.1f} GB). "
            "Delete files or purchase more storage, then retry the job."
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
