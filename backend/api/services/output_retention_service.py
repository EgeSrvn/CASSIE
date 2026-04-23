"""
Automatic retention cleanup for old job outputs.

When a finished job falls outside the user's retained finished-job window,
its output files and generated ZIP archives are purged from storage.
"""

from typing import Any, Dict, List, Optional, Tuple

from backend.api.database.db_init import get_db_connection
from backend.api.models.pipeline_model import FileType
from backend.api.services.minio_client import get_minio_client
from backend.api.services.storage_service import (
    delete_file_records_for_job,
    get_files_by_user,
)
from backend.api.services.user_limit_service import TERMINAL_JOB_STATUSES, get_user_limits
from backend.api.services.user_service import get_user_by_id
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def _resolve_username(user_id: int, username: Optional[str]) -> Optional[str]:
    if username:
        return username
    user = get_user_by_id(user_id)
    return user.username if user else None


def _get_output_retention_limit(username: Optional[str]) -> int:
    limits = get_user_limits(username)
    downloadable_limit = max(int(limits.get("downloadable_finished_jobs", 0)), 0)
    interactive_limit = max(int(limits.get("interactive_output_jobs", 0)), 0)
    return max(downloadable_limit, interactive_limit)


def get_expired_finished_job_ids_for_user(user_id: int, username: Optional[str]) -> Tuple[List[int], int]:
    retained_finished_jobs = _get_output_retention_limit(username)

    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                WITH ranked_finished_jobs AS (
                    SELECT
                        id,
                        ROW_NUMBER() OVER (
                            ORDER BY COALESCE(updated_at, created_at) DESC, id DESC
                        ) AS finished_rank
                    FROM jobs
                    WHERE user_id = %s
                      AND status = ANY(%s)
                )
                SELECT id
                FROM ranked_finished_jobs
                WHERE finished_rank > %s
                ORDER BY finished_rank ASC, id ASC
                """,
                (user_id, list(TERMINAL_JOB_STATUSES), retained_finished_jobs),
            )
            return [int(row[0]) for row in cur.fetchall()], retained_finished_jobs
        finally:
            cur.close()


def purge_job_output_artifacts(job_id: int, user_id: int, username: Optional[str]) -> Dict[str, Any]:
    resolved_username = _resolve_username(user_id, username)
    minio_client = get_minio_client()
    output_files = get_files_by_user(
        user_id=user_id,
        job_id=job_id,
        file_type=FileType.OUTPUT,
        limit=10000,
        offset=0,
    )

    deleted_object_count = 0
    deletion_errors: List[str] = []

    for file_record in output_files:
        s3_key = getattr(file_record, "s3_key", None)
        if not s3_key:
            continue
        try:
            minio_client.delete_file(
                user_id=user_id,
                s3_key=s3_key,
                username=resolved_username,
            )
            deleted_object_count += 1
        except Exception as cleanup_error:
            message = f"Failed to delete output object '{s3_key}' for job {job_id}: {cleanup_error}"
            logger.warning(message, exc_info=True)
            deletion_errors.append(message)

    deleted_record_count = delete_file_records_for_job(
        user_id=user_id,
        job_id=job_id,
        file_type=FileType.OUTPUT,
    )

    deleted_archive_count = 0
    try:
        from backend.api.services.job_archive_service import clear_job_outputs_zip_artifacts

        deleted_archive_count = clear_job_outputs_zip_artifacts(
            job_id=job_id,
            user_id=user_id,
            username=resolved_username,
        )
    except Exception as cleanup_error:
        message = f"Failed to clear ZIP archive artifacts for job {job_id}: {cleanup_error}"
        logger.warning(message, exc_info=True)
        deletion_errors.append(message)

    if deleted_record_count or deleted_object_count or deleted_archive_count:
        logger.info(
            "Purged expired outputs for job %s: %s database record(s), %s object(s), %s archive object(s)",
            job_id,
            deleted_record_count,
            deleted_object_count,
            deleted_archive_count,
        )

    return {
        "job_id": job_id,
        "deleted_record_count": deleted_record_count,
        "deleted_object_count": deleted_object_count,
        "deleted_archive_count": deleted_archive_count,
        "errors": deletion_errors,
    }


def purge_expired_finished_job_outputs_for_user(user_id: int, username: Optional[str] = None) -> Dict[str, Any]:
    resolved_username = _resolve_username(user_id, username)
    expired_job_ids, retained_finished_jobs = get_expired_finished_job_ids_for_user(user_id, resolved_username)

    purged_jobs: List[Dict[str, Any]] = []
    total_deleted_records = 0
    total_deleted_objects = 0
    total_deleted_archives = 0

    for job_id in expired_job_ids:
        purge_summary = purge_job_output_artifacts(job_id, user_id, resolved_username)
        purged_jobs.append(purge_summary)
        total_deleted_records += int(purge_summary.get("deleted_record_count", 0))
        total_deleted_objects += int(purge_summary.get("deleted_object_count", 0))
        total_deleted_archives += int(purge_summary.get("deleted_archive_count", 0))

    return {
        "retained_finished_jobs": retained_finished_jobs,
        "expired_job_ids": expired_job_ids,
        "purged_jobs": purged_jobs,
        "deleted_record_count": total_deleted_records,
        "deleted_object_count": total_deleted_objects,
        "deleted_archive_count": total_deleted_archives,
    }
