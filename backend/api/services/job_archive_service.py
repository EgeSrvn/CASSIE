import os
import tempfile
import time
import urllib.parse
import zipfile
from threading import Lock, Thread
from typing import Any, Dict, Optional, Tuple

from backend.api.models.pipeline_model import FileType
from backend.api.services.job_service import get_job_by_id
from backend.api.services.minio_client import get_minio_client
from backend.api.services.storage_service import get_files_by_user
from backend.api.services.user_service import get_user_by_id
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)
minio_client = get_minio_client()

ZIP_DOWNLOAD_EXPIRATION_SECONDS = 3600
zip_download_jobs: Dict[Tuple[int, int], Dict[str, Any]] = {}
zip_download_jobs_lock = Lock()


def _get_zip_job_key(user_id: int, job_id: int) -> Tuple[int, int]:
    return (user_id, job_id)


def _sanitize_job_names(job_id: int, job_name: str) -> Tuple[str, str]:
    display_fragment = "".join(c for c in job_name if c.isalnum() or c in (" ", "-", "_")).rstrip()
    filename_fragment = display_fragment or f"job_{job_id}"
    safe_job_fragment = "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in job_name).strip("_")
    if not safe_job_fragment:
        safe_job_fragment = f"job_{job_id}"
    return filename_fragment, safe_job_fragment


def _job_zip_artifact_details(job_id: int, job_name: str) -> Tuple[str, str]:
    filename_fragment, safe_job_fragment = _sanitize_job_names(job_id, job_name)
    zip_filename = f"job_{job_id}_{filename_fragment}_outputs.zip"
    zip_s3_key = f"generated-archives/jobs/{job_id}/{safe_job_fragment}_outputs.zip"
    return zip_filename, zip_s3_key


def _set_zip_download_status(user_id: int, job_id: int, **values: Any) -> None:
    job_key = _get_zip_job_key(user_id, job_id)
    with zip_download_jobs_lock:
        current = zip_download_jobs.get(job_key, {})
        current.update(values)
        current["updated_at"] = time.time()
        zip_download_jobs[job_key] = current


def _build_ready_payload(user_id: int, username: str, job_id: int, job_name: str) -> Optional[Dict[str, Any]]:
    zip_filename, zip_s3_key = _job_zip_artifact_details(job_id, job_name)
    if not minio_client.file_exists(user_id=user_id, s3_key=zip_s3_key, username=username):
        return None

    content_disposition = (
        f'attachment; filename="{zip_filename}"; '
        f"filename*=UTF-8''{urllib.parse.quote(zip_filename, safe='')}"
    )
    download_url = minio_client.generate_presigned_url(
        user_id=user_id,
        s3_key=zip_s3_key,
        username=username,
        expiration=ZIP_DOWNLOAD_EXPIRATION_SECONDS,
        response_content_disposition=content_disposition,
    )
    return {
        "status": "ready",
        "download_url": download_url,
        "filename": zip_filename,
        "expires_in": ZIP_DOWNLOAD_EXPIRATION_SECONDS,
        "expires_at": time.time() + ZIP_DOWNLOAD_EXPIRATION_SECONDS,
        "error": None,
    }


def get_zip_download_status_payload(
    user_id: int,
    job_id: int,
    username: Optional[str] = None,
) -> Dict[str, Any]:
    job_key = _get_zip_job_key(user_id, job_id)
    with zip_download_jobs_lock:
        status_data = zip_download_jobs.get(job_key)

    if not status_data:
        if username:
            job = get_job_by_id(job_id, user_id=user_id)
            if job is not None:
                ready_payload = _build_ready_payload(user_id, username, job_id, job.name)
                if ready_payload:
                    _set_zip_download_status(user_id, job_id, **ready_payload)
                    return ready_payload
        return {
            "status": "idle",
            "download_url": None,
            "filename": None,
            "expires_in": None,
            "error": None,
        }

    payload = dict(status_data)
    expires_at = payload.get("expires_at")
    if payload.get("status") == "ready" and expires_at and time.time() >= expires_at:
        if username:
            job = get_job_by_id(job_id, user_id=user_id)
            if job is not None:
                ready_payload = _build_ready_payload(user_id, username, job_id, job.name)
                if ready_payload:
                    _set_zip_download_status(user_id, job_id, **ready_payload)
                    return ready_payload
        payload.update({
            "status": "expired",
            "download_url": None,
            "error": "Download link expired. Generate a new ZIP link to continue.",
        })
        _set_zip_download_status(user_id, job_id, **payload)

    if payload.get("status") != "ready":
        payload["download_url"] = None

    return payload


def _build_job_outputs_zip_for_download(job_id: int, user_id: int, username: str) -> Dict[str, Any]:
    job = get_job_by_id(job_id, user_id=user_id)
    if job is None:
        raise FileNotFoundError(f"Job {job_id} not found")

    output_files = get_files_by_user(
        user_id=user_id,
        job_id=job_id,
        file_type=FileType.OUTPUT,
        limit=1000,
        offset=0,
    )
    if not output_files:
        raise ValueError("No output files found for this job")

    zip_filename, zip_s3_key = _job_zip_artifact_details(job_id, job.name)

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name
    temp_zip.close()
    added_files = 0

    try:
        with zipfile.ZipFile(temp_zip_path, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for file_record in output_files:
                temp_file = tempfile.NamedTemporaryFile(delete=False)
                temp_path = temp_file.name
                temp_file.close()
                try:
                    minio_client.download_file(
                        user_id=user_id,
                        s3_key=file_record.s3_key,
                        local_path=temp_path,
                        username=username,
                    )
                    zip_file.write(temp_path, file_record.filename)
                    added_files += 1
                    logger.info(f"Added {file_record.filename} to ZIP archive for job {job_id}")
                except Exception as exc:
                    logger.warning(f"Failed to add {file_record.filename} to ZIP for job {job_id}: {exc}")
                finally:
                    if os.path.exists(temp_path):
                        try:
                            os.unlink(temp_path)
                        except Exception as exc:
                            logger.warning(f"Failed to delete temp file {temp_path}: {exc}")

        if added_files == 0:
            raise RuntimeError("Failed to create ZIP archive because no output files could be packaged")

        minio_client.upload_file(
            user_id=user_id,
            local_path=temp_zip_path,
            s3_key=zip_s3_key,
            username=username,
            metadata={"job-id": str(job_id), "archive-type": "job-outputs-zip"},
        )
        ready_payload = _build_ready_payload(user_id, username, job_id, job.name)
        if ready_payload is None:
            raise RuntimeError("ZIP archive upload succeeded but download link could not be generated")
        return ready_payload
    finally:
        if os.path.exists(temp_zip_path):
            try:
                os.unlink(temp_zip_path)
            except Exception as exc:
                logger.warning(f"Failed to delete temp ZIP file {temp_zip_path}: {exc}")


def _generate_job_outputs_zip_in_background(job_id: int, user_id: int, username: str) -> None:
    try:
        _set_zip_download_status(
            user_id,
            job_id,
            status="processing",
            download_url=None,
            filename=None,
            expires_in=None,
            expires_at=None,
            error=None,
        )
        result = _build_job_outputs_zip_for_download(job_id, user_id, username)
        _set_zip_download_status(user_id, job_id, **result)
    except Exception as exc:
        logger.error(f"Error creating ZIP archive for job {job_id}: {exc}", exc_info=True)
        _set_zip_download_status(
            user_id,
            job_id,
            status="failed",
            download_url=None,
            filename=None,
            expires_in=None,
            expires_at=None,
            error=str(exc) or "Failed to create ZIP archive",
        )


def request_job_outputs_zip_generation(job_id: int, user_id: int, username: str) -> Dict[str, Any]:
    status_payload = get_zip_download_status_payload(user_id, job_id, username=username)
    if status_payload["status"] in {"queued", "processing", "ready"}:
        return status_payload

    _set_zip_download_status(
        user_id,
        job_id,
        status="queued",
        download_url=None,
        filename=None,
        expires_in=None,
        expires_at=None,
        error=None,
    )
    Thread(
        target=_generate_job_outputs_zip_in_background,
        args=(job_id, user_id, username),
        daemon=True,
    ).start()
    return get_zip_download_status_payload(user_id, job_id, username=username)


def prewarm_job_outputs_zip(job_id: int, user_id: int, username: Optional[str] = None) -> None:
    resolved_username = username
    if not resolved_username:
        user = get_user_by_id(user_id)
        resolved_username = user.username if user else None
    if not resolved_username:
        logger.warning(f"Skipping ZIP prewarm for job {job_id}: username could not be resolved")
        return
    request_job_outputs_zip_generation(job_id, user_id, resolved_username)


def clear_job_outputs_zip_artifacts(job_id: int, user_id: int, username: Optional[str] = None) -> int:
    job_key = _get_zip_job_key(user_id, job_id)
    with zip_download_jobs_lock:
        zip_download_jobs.pop(job_key, None)

    return minio_client.delete_prefix(
        user_id=user_id,
        prefix=f"generated-archives/jobs/{job_id}/",
        username=username,
    )
