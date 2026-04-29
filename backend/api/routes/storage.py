"""
Storage management routes for CASSIE backend.

This module provides:
- File upload
- List user files
- Get file details
- Download files
- Delete files
"""

import os
import time
import tempfile
import hashlib
import shutil
from pydantic import BaseModel, Field
from fastapi.concurrency import run_in_threadpool
from fastapi import APIRouter, BackgroundTasks, Depends, UploadFile, File, HTTPException, status, Query, Request
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from typing import Optional, List
# Use real JWT auth (Task 5.4 - now fixed)
from backend.api.routes.auth import get_current_user, get_auth_context, AuthContext
from backend.api.models.user_model import UserResponse
from backend.api.models.pipeline_model import (
    FileCreate,
    FileUpdate,
    FileResponse,
    FileType
)
from backend.api.services.storage_service import (
    create_file_record,
    get_existing_file_record_by_fingerprint,
    get_file_by_id,
    get_files_by_user,
    get_total_file_bytes_by_user,
    prune_missing_file_records_by_user,
    update_file,
    delete_file_record,
    count_files_by_user
)
from backend.api.services.minio_client import MinIOClient, get_minio_client
from backend.api.services.billing_service import charge_user_cash_balance
from backend.api.services.job_archive_service import (
    get_zip_download_status_payload,
    request_job_outputs_zip_generation,
)
from backend.api.services.job_service import get_job_by_id
from backend.api.services.job_launch_service import get_auto_start_payload, start_job_execution_task
from backend.api.services.user_service import get_user_by_id
from backend.api.services.user_limit_service import (
    can_user_access_job_outputs,
    get_user_active_storage_subscription,
    get_storage_upgrade_plan,
    get_user_limits,
    set_user_storage_subscription,
    validate_user_storage_capacity,
    validate_output_file_access,
)
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    not_found_response,
    paginated_response,
    ErrorCode
)
from backend.api.utils.validators import (
    validate_file_type,
    validate_file_format
)
from backend.api.utils.logger import get_logger
from backend.api.routes.data_files import _download_google_drive_file

logger = get_logger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])

# Initialize MinIO client
minio_client = get_minio_client()
ZIP_DOWNLOAD_EXPIRATION_SECONDS = 3600


def _write_upload_chunk(temp_file, hash_md5, chunk: bytes) -> None:
    hash_md5.update(chunk)
    temp_file.write(chunk)


class GoogleDriveStorageImportRequest(BaseModel):
    file_id: str = Field(..., min_length=5, max_length=512)
    access_token: str = Field(..., min_length=20, max_length=8192)
    filename: str = Field(..., min_length=1, max_length=255)
    mime_type: Optional[str] = Field(None, max_length=255)
    file_format: Optional[str] = Field(None, max_length=50)


class StorageFileUpdateRequest(BaseModel):
    filename: Optional[str] = Field(None, min_length=1, max_length=255)
    file_format: Optional[str] = Field(None, max_length=50)


class StorageUpgradePurchaseRequest(BaseModel):
    plan_id: str = Field(..., min_length=1, max_length=120)


@router.get("/summary", status_code=status.HTTP_200_OK)
async def get_storage_summary(
    current_user: UserResponse = Depends(get_current_user),
):
    """Return storage quota and usage for the current user."""
    try:
        limits = await run_in_threadpool(get_user_limits, current_user.username)
        await run_in_threadpool(
            prune_missing_file_records_by_user,
            current_user.id,
            current_user.username,
        )
        used_bytes = await run_in_threadpool(get_total_file_bytes_by_user, current_user.id)
        max_storage_bytes = max(int(limits.get("max_storage_bytes", 0)), 0)
        remaining_bytes = max(max_storage_bytes - used_bytes, 0) if max_storage_bytes > 0 else None

        return success_response(
            data={
                "used_bytes": used_bytes,
                "max_storage_bytes": max_storage_bytes,
                "remaining_bytes": remaining_bytes,
                "usage_ratio": (used_bytes / max_storage_bytes) if max_storage_bytes > 0 else None,
                "subscription_upgrade_available": True,
                "subscription_period": "weekly",
                "active_subscription": get_user_active_storage_subscription(current_user.username),
            },
            message="Storage summary retrieved successfully",
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Error getting storage summary: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve storage summary",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/upgrade/purchase", status_code=status.HTTP_200_OK)
async def purchase_storage_upgrade(
    payload: StorageUpgradePurchaseRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Charge the user balance and increase their storage quota."""
    try:
        plan = get_storage_upgrade_plan(payload.plan_id)
        if not plan:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Selected storage plan was not found.",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

        charge_user_cash_balance(current_user.id, plan.get("weekly_price", 0))
        updated_limits = set_user_storage_subscription(
            current_user.username,
            payload.plan_id,
        )
        updated_user = get_user_by_id(current_user.id)
        used_bytes = get_total_file_bytes_by_user(current_user.id)
        max_storage_bytes = max(int(updated_limits.get("max_storage_bytes", 0)), 0)

        return success_response(
            data={
                "plan_id": str(plan.get("id") or ""),
                "plan_name": str(plan.get("name") or "Storage upgrade"),
                "additional_gb": float(plan.get("additional_gb", 0) or 0),
                "weekly_price": float(plan.get("weekly_price", 0) or 0),
                "user": {
                    "cash_balance_usd": float(getattr(updated_user, "cash_balance_usd", 0) or 0),
                    "cash_reserved_usd": float(getattr(updated_user, "cash_reserved_usd", 0) or 0),
                    "cash_available_usd": max(float(getattr(updated_user, "cash_balance_usd", 0) or 0), 0.0),
                } if updated_user else None,
                "storage": {
                    "used_bytes": used_bytes,
                    "max_storage_bytes": max_storage_bytes,
                    "remaining_bytes": max(max_storage_bytes - used_bytes, 0) if max_storage_bytes > 0 else None,
                    "usage_ratio": (used_bytes / max_storage_bytes) if max_storage_bytes > 0 else None,
                    "active_subscription": get_user_active_storage_subscription(current_user.username),
                },
            },
            message="Storage upgrade purchased successfully",
            status_code=status.HTTP_200_OK,
        )
    except ValueError as exc:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as exc:
        logger.error(f"Error purchasing storage upgrade: {exc}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to purchase storage upgrade",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


def _hash_local_file_md5(local_path: str) -> str:
    hash_md5 = hashlib.md5()
    with open(local_path, "rb") as source:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            hash_md5.update(chunk)
    return hash_md5.hexdigest()


def _parse_content_length(request: Request) -> Optional[int]:
    raw_value = request.headers.get("content-length")
    if not raw_value:
        return None
    try:
        return max(int(raw_value), 0)
    except ValueError:
        return None


def _queue_job_start_if_uploads_complete(
    background_tasks: BackgroundTasks,
    *,
    job_id: Optional[int],
    user_id: int,
    expected_total_input_files: Optional[int],
) -> None:
    if job_id is None or not expected_total_input_files or expected_total_input_files <= 0:
        return

    input_files = get_files_by_user(
        user_id=user_id,
        job_id=job_id,
        file_type=FileType.INPUT,
        limit=max(expected_total_input_files, 100),
        offset=0,
    )
    if len(input_files) < expected_total_input_files:
        return

    job, input_file_ids, readiness_error = get_auto_start_payload(job_id, user_id)
    if readiness_error or not job or not input_file_ids:
        logger.info(
            "Job %s has %s/%s uploaded input files but is not ready to auto-start: %s",
            job_id,
            len(input_files),
            expected_total_input_files,
            readiness_error or "missing input files",
        )
        return

    background_tasks.add_task(
        start_job_execution_task,
        job_id,
        user_id,
        job.workflow_id,
        input_file_ids,
    )


@router.put("/files/{file_id}", status_code=status.HTTP_200_OK)
async def update_storage_file(
    file_id: int,
    payload: StorageFileUpdateRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    file_record = get_file_by_id(file_id, user_id=current_user.id)
    if file_record is None:
        error_data = not_found_response("File", file_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    if payload.file_format:
        is_valid, error_msg = validate_file_format(payload.file_format)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    updated_file = update_file(
        file_id,
        current_user.id,
        FileUpdate(
            filename=payload.filename,
            file_format=payload.file_format,
        ),
    )
    if updated_file is None:
        error_data = not_found_response("File", file_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    return JSONResponse(
        content=success_response(
            data=FileResponse(
                id=updated_file.id,
                job_id=updated_file.job_id,
                filename=updated_file.filename,
                s3_key=updated_file.s3_key,
                file_type=updated_file.file_type,
                file_format=updated_file.file_format,
                size_bytes=updated_file.size_bytes,
                checksum=updated_file.checksum,
                uploaded_at=updated_file.uploaded_at,
                created_at=updated_file.created_at,
            ).model_dump(mode="json"),
            message="File updated successfully",
            status_code=status.HTTP_200_OK,
        ),
        status_code=status.HTTP_200_OK,
    )

@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(
    request: Request,
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    job_id: Optional[int] = Query(None, description="Job ID to associate file with (optional for pre-upload)"),
    file_type: FileType = Query(..., description="Type of file (input, output, intermediate, log)"),
    file_format: Optional[str] = Query(None, description="File format (fastq, fasta, etc.)"),
    auth_context: AuthContext = Depends(get_auth_context)
):
    """
    Upload a file. Can be associated with a job immediately or stored for later association.
    
    Args:
        file: Uploaded file
        job_id: Optional Job ID to associate file with. If None, file is stored in user's staging area.
        file_type: Type of file
        file_format: Optional file format
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with file data (including file_id for later job association)
    """
    current_user = auth_context.user
    request_size = _parse_content_length(request)
    logger.info(
        "Upload request accepted for user %s job %s file %s (%s bytes declared)",
        current_user.id,
        job_id,
        file.filename,
        request_size if request_size is not None else "unknown",
    )
    if request_size is not None:
        storage_ok, storage_error = await run_in_threadpool(
            validate_user_storage_capacity,
            current_user.id,
            current_user.username,
            request_size,
            shutil.disk_usage(tempfile.gettempdir()).free,
        )
        if not storage_ok:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=storage_error,
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

    if auth_context.token_type == "job_upload_session":
        if job_id is None or job_id != auth_context.job_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Upload session token can only upload files for its job",
            )
        if file_type != FileType.INPUT:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Upload session token can only upload input files",
            )

    # If job_id is provided, verify job exists and belongs to user
    if job_id is not None:
        job = get_job_by_id(job_id, user_id=current_user.id)
        if job is None:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    # Validate file type
    is_valid, error_msg = validate_file_type(file_type.value)
    if not is_valid:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Validate file format if provided
    if file_format:
        is_valid, error_msg = validate_file_format(file_format)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Save uploaded file to temporary location
    temp_path: Optional[str] = None
    try:
        hash_md5 = hashlib.md5()
        file_size = 0
        chunk_size = 1024 * 1024

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_path = temp_file.name

            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                await run_in_threadpool(_write_upload_chunk, temp_file, hash_md5, chunk)

            await run_in_threadpool(temp_file.flush)

        checksum = hash_md5.hexdigest()
        logger.info(
            "Upload body received for user %s job %s file %s (%s bytes). Storing object...",
            current_user.id,
            job_id,
            file.filename,
            file_size,
        )

        storage_ok, storage_error = await run_in_threadpool(
            validate_user_storage_capacity,
            current_user.id,
            current_user.username,
            file_size,
            shutil.disk_usage(temp_path).free,
        )
        if not storage_ok:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=storage_error,
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE)

        if job_id:
            s3_key = f"jobs/{job_id}/{file_type.value}/{file.filename}"
            existing_file = await run_in_threadpool(
                get_existing_file_record_by_fingerprint,
                job_id=job_id,
                filename=file.filename,
                file_type=file_type,
                size_bytes=file_size,
                checksum=checksum,
            )
            if existing_file:
                logger.info(
                    "Duplicate upload request for job %s file %s matched existing file record %s; returning existing record.",
                    job_id,
                    file.filename,
                    existing_file.id,
                )
                response_data = success_response(
                    data=FileResponse(
                        id=existing_file.id,
                        job_id=existing_file.job_id,
                        filename=existing_file.filename,
                        s3_key=existing_file.s3_key,
                        file_type=existing_file.file_type,
                        file_format=existing_file.file_format,
                        size_bytes=existing_file.size_bytes,
                        checksum=existing_file.checksum,
                        uploaded_at=existing_file.uploaded_at,
                        created_at=existing_file.created_at,
                    ).model_dump(mode='json'),
                    message="File already uploaded",
                    status_code=status.HTTP_201_CREATED,
                )
                return JSONResponse(content=response_data, status_code=status.HTTP_201_CREATED)
        else:
            s3_key = f"staging/{current_user.id}/{int(time.time())}_{file.filename}"

        await run_in_threadpool(
            minio_client.ensure_user_bucket,
            current_user.id,
            current_user.username,
        )

        upload_result = await run_in_threadpool(
            minio_client.upload_file,
            current_user.id,
            temp_path,
            s3_key,
            current_user.username,
        )
        logger.info(
            "Object stored for user %s job %s file %s at %s",
            current_user.id,
            job_id,
            file.filename,
            upload_result.get("object_key") or upload_result.get("key"),
        )

        file_data = FileCreate(
            job_id=job_id,
            filename=file.filename,
            s3_key=s3_key,
            file_type=file_type,
            file_format=file_format,
            size_bytes=file_size,
            checksum=checksum
        )

        file_record = await run_in_threadpool(create_file_record, file_data)
        logger.info(
            "File record %s created for user %s job %s file %s",
            file_record.id,
            current_user.id,
            job_id,
            file.filename,
        )

        if job_id and file_type == FileType.INPUT:
            logger.info(
                "Input file uploaded to pending job %s. Job execution is controlled by the upload queue.",
                job_id,
            )
            _queue_job_start_if_uploads_complete(
                background_tasks,
                job_id=job_id,
                user_id=current_user.id,
                expected_total_input_files=auth_context.expected_total_input_files,
            )

        response_data = success_response(
            data=FileResponse(
                id=file_record.id,
                job_id=file_record.job_id,
                filename=file_record.filename,
                s3_key=file_record.s3_key,
                file_type=file_record.file_type,
                file_format=file_record.file_format,
                size_bytes=file_record.size_bytes,
                checksum=file_record.checksum,
                uploaded_at=file_record.uploaded_at,
                created_at=file_record.created_at
            ).model_dump(mode='json'),
            message="File uploaded successfully",
            status_code=status.HTTP_201_CREATED
        )
        return JSONResponse(content=response_data, status_code=status.HTTP_201_CREATED)
            
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error uploading file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to upload file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_path}: {e}")


@router.post("/import-google-drive", status_code=status.HTTP_201_CREATED)
async def import_google_drive_file_to_job(
    payload: GoogleDriveStorageImportRequest,
    background_tasks: BackgroundTasks,
    job_id: Optional[int] = Query(None, description="Job ID to associate file with, or omit to import to staging"),
    auth_context: AuthContext = Depends(get_auth_context),
):
    """
    Import a user-selected Google Drive file directly into a pending job input area.
    """
    current_user = auth_context.user

    if auth_context.token_type == "job_upload_session" and (job_id is None or job_id != auth_context.job_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Upload session token can only import files for its job",
        )

    if job_id is not None:
        job = get_job_by_id(job_id, user_id=current_user.id)
        if job is None:
            return JSONResponse(content=not_found_response("Job", job_id), status_code=status.HTTP_404_NOT_FOUND)

    if payload.file_format:
        is_valid, error_msg = validate_file_format(payload.file_format)
        if not is_valid:
            return JSONResponse(
                content=error_response(
                    error_code=ErrorCode.VALIDATION_ERROR,
                    message=error_msg,
                    status_code=status.HTTP_400_BAD_REQUEST,
                ),
                status_code=status.HTTP_400_BAD_REQUEST,
            )

    temp_path: Optional[str] = None
    try:
        temp_path, filename = await run_in_threadpool(
            _download_google_drive_file,
            payload.file_id,
            payload.access_token,
            payload.filename,
            payload.mime_type,
        )
        file_size = await run_in_threadpool(os.path.getsize, temp_path)
        checksum = await run_in_threadpool(_hash_local_file_md5, temp_path)
        s3_key = f"jobs/{job_id}/input/{filename}" if job_id is not None else f"staging/{current_user.id}/{int(time.time())}_{filename}"

        storage_ok, storage_error = await run_in_threadpool(
            validate_user_storage_capacity,
            current_user.id,
            current_user.username,
            file_size,
            shutil.disk_usage(temp_path).free,
        )
        if not storage_ok:
            return JSONResponse(
                content=error_response(
                    error_code=ErrorCode.VALIDATION_ERROR,
                    message=storage_error,
                    status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                ),
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            )

        existing_file = await run_in_threadpool(
            get_existing_file_record_by_fingerprint,
            job_id=job_id,
            filename=filename,
            file_type=FileType.INPUT,
            size_bytes=file_size,
            checksum=checksum,
        )
        if existing_file:
            if job_id is not None:
                _queue_job_start_if_uploads_complete(
                    background_tasks,
                    job_id=job_id,
                    user_id=current_user.id,
                    expected_total_input_files=auth_context.expected_total_input_files,
                )
            response_data = success_response(
                data=FileResponse(
                    id=existing_file.id,
                    job_id=existing_file.job_id,
                    filename=existing_file.filename,
                    s3_key=existing_file.s3_key,
                    file_type=existing_file.file_type,
                    file_format=existing_file.file_format,
                    size_bytes=existing_file.size_bytes,
                    checksum=existing_file.checksum,
                    uploaded_at=existing_file.uploaded_at,
                    created_at=existing_file.created_at,
                ).model_dump(mode="json"),
                message="File already imported",
                status_code=status.HTTP_201_CREATED,
            )
            return JSONResponse(content=response_data, status_code=status.HTTP_201_CREATED)

        await run_in_threadpool(
            minio_client.ensure_user_bucket,
            current_user.id,
            current_user.username,
        )
        await run_in_threadpool(
            minio_client.upload_file,
            current_user.id,
            temp_path,
            s3_key,
            current_user.username,
        )

        file_record = await run_in_threadpool(
            create_file_record,
            FileCreate(
                job_id=job_id,
                filename=filename,
                s3_key=s3_key,
                file_type=FileType.INPUT,
                file_format=payload.file_format,
                size_bytes=file_size,
                checksum=checksum,
            ),
        )
        if job_id is not None:
            _queue_job_start_if_uploads_complete(
                background_tasks,
                job_id=job_id,
                user_id=current_user.id,
                expected_total_input_files=auth_context.expected_total_input_files,
            )

        response_data = success_response(
            data=FileResponse(
                id=file_record.id,
                job_id=file_record.job_id,
                filename=file_record.filename,
                s3_key=file_record.s3_key,
                file_type=file_record.file_type,
                file_format=file_record.file_format,
                size_bytes=file_record.size_bytes,
                checksum=file_record.checksum,
                uploaded_at=file_record.uploaded_at,
                created_at=file_record.created_at,
            ).model_dump(mode="json"),
            message="Google Drive file imported successfully",
            status_code=status.HTTP_201_CREATED,
        )
        return JSONResponse(content=response_data, status_code=status.HTTP_201_CREATED)
    except ValueError as e:
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=str(e),
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
    except Exception as e:
        logger.error(f"Error importing Google Drive file to job {job_id}: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to import Google Drive file",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp file {temp_path}: {e}")


@router.get("/files")
async def list_files(
    job_id: Optional[int] = Query(None, description="Filter by job ID"),
    file_type: Optional[FileType] = Query(None, description="Filter by file type"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=1000, description="Items per page"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List user's files with optional filters and pagination.
    
    Args:
        job_id: Optional job ID filter
        file_type: Optional file type filter
        page: Page number (1-indexed)
        per_page: Number of items per page
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Paginated response with list of files
    """
    try:
        offset = (page - 1) * per_page
        files = get_files_by_user(
            user_id=current_user.id,
            job_id=job_id,
            file_type=file_type,
            limit=per_page,
            offset=offset
        )
        
        total = count_files_by_user(current_user.id, job_id, file_type)
        
        file_responses = [
            FileResponse(
                id=file.id,
                job_id=file.job_id,
                filename=file.filename,
                s3_key=file.s3_key,
                file_type=file.file_type,
                file_format=file.file_format,
                size_bytes=file.size_bytes,
                checksum=file.checksum,
                uploaded_at=file.uploaded_at,
                created_at=file.created_at
            ).model_dump(mode='json')
            for file in files
        ]
        
        return paginated_response(
            data=file_responses,
            page=page,
            per_page=per_page,
            total=total,
            message="Files retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error listing files: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve files",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/files/{file_id}")
async def get_file(
    file_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get file details by ID.
    
    Args:
        file_id: File ID
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with file data
    """
    file_record = get_file_by_id(file_id, user_id=current_user.id)
    
    if file_record is None:
        error_data = not_found_response("File", file_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    return success_response(
        data=FileResponse(
            id=file_record.id,
            job_id=file_record.job_id,
            filename=file_record.filename,
            s3_key=file_record.s3_key,
            file_type=file_record.file_type,
            file_format=file_record.file_format,
            size_bytes=file_record.size_bytes,
            checksum=file_record.checksum,
            uploaded_at=file_record.uploaded_at,
            created_at=file_record.created_at
        ).model_dump(mode='json'),
        message="File retrieved successfully"
    )


@router.get("/files/{file_id}/download")
async def download_file(
    file_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Download a file.
    
    Args:
        file_id: File ID
        current_user: Current authenticated user (from dependency)
        
    Returns:
        File download stream
    """
    # Get file record
    file_record = get_file_by_id(file_id, user_id=current_user.id)
    
    if file_record is None:
        error_data = not_found_response("File", file_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    allowed, access_error = validate_output_file_access(file_record, current_user.id, current_user.username)
    if not allowed:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=access_error or "Output access is not allowed for this file",
            status_code=status.HTTP_403_FORBIDDEN
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)
    
    try:
        # Download file to temp location
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        try:
            # Download from MinIO
            minio_client.download_file(
                user_id=current_user.id,
                s3_key=file_record.s3_key,
                local_path=temp_path,
                username=current_user.username
            )
            
            # Read file content
            def generate():
                with open(temp_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)  # Read in 8KB chunks
                        if not chunk:
                            break
                        yield chunk
                # Clean up temp file after streaming
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {temp_path}: {e}")
            
            # Determine content type based on file extension
            filename_lower = file_record.filename.lower()
            if filename_lower.endswith('.html'):
                media_type = 'text/html'
            elif filename_lower.endswith(('.png', '.jpg', '.jpeg', '.gif')):
                media_type = f'image/{filename_lower.split(".")[-1]}'
            elif filename_lower.endswith('.pdf'):
                media_type = 'application/pdf'
            elif filename_lower.endswith('.zip'):
                media_type = 'application/zip'
            else:
                media_type = 'application/octet-stream'
            
            return StreamingResponse(
                generate(),
                media_type=media_type,
                headers={
                    "Content-Disposition": f'attachment; filename="{file_record.filename}"',
                }
            )
            
        except Exception as download_error:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            raise download_error
        
    except Exception as e:
        logger.error(f"Error downloading file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to download file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/files/{file_id}/view")
async def view_file(
    file_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get file content for viewing (for images, HTML, etc.).
    
    Args:
        file_id: File ID
        current_user: Current authenticated user (from dependency)
        
    Returns:
        File content stream with appropriate content type
    """
    # Get file record
    file_record = get_file_by_id(file_id, user_id=current_user.id)
    
    if file_record is None:
        error_data = not_found_response("File", file_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    allowed, access_error = validate_output_file_access(file_record, current_user.id, current_user.username)
    if not allowed:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=access_error or "Output access is not allowed for this file",
            status_code=status.HTTP_403_FORBIDDEN
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)
    
    try:
        # Download file to temp location
        temp_file = tempfile.NamedTemporaryFile(delete=False)
        temp_path = temp_file.name
        temp_file.close()
        
        try:
            # Download from MinIO
            minio_client.download_file(
                user_id=current_user.id,
                s3_key=file_record.s3_key,
                local_path=temp_path,
                username=current_user.username
            )
            
            # Read file content
            def generate():
                with open(temp_path, 'rb') as f:
                    while True:
                        chunk = f.read(8192)  # Read in 8KB chunks
                        if not chunk:
                            break
                        yield chunk
                # Clean up temp file after streaming
                try:
                    os.unlink(temp_path)
                except Exception as e:
                    logger.warning(f"Failed to delete temp file {temp_path}: {e}")
            
            # Determine content type based on file extension
            filename_lower = file_record.filename.lower()
            if filename_lower.endswith('.html'):
                media_type = 'text/html'
            elif filename_lower.endswith('.png'):
                media_type = 'image/png'
            elif filename_lower.endswith(('.jpg', '.jpeg')):
                media_type = 'image/jpeg'
            elif filename_lower.endswith('.gif'):
                media_type = 'image/gif'
            elif filename_lower.endswith('.pdf'):
                media_type = 'application/pdf'
            elif filename_lower.endswith('.svg'):
                media_type = 'image/svg+xml'
            else:
                media_type = 'application/octet-stream'
            
            return StreamingResponse(
                generate(),
                media_type=media_type,
                headers={
                    "Content-Disposition": f'inline; filename="{file_record.filename}"',
                }
            )
            
        except Exception as download_error:
            # Clean up temp file on error
            if os.path.exists(temp_path):
                try:
                    os.unlink(temp_path)
                except:
                    pass
            raise download_error
        
    except Exception as e:
        logger.error(f"Error viewing file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to view file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/jobs/{job_id}/download-zip")
async def request_job_outputs_zip(
    job_id: int,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Start background generation of a ZIP archive for all job outputs.
    """
    job = get_job_by_id(job_id, user_id=current_user.id)
    if job is None:
        error_data = not_found_response("Job", job_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    can_access_outputs, max_finished_jobs = can_user_access_job_outputs(
        user_id=current_user.id,
        username=current_user.username,
        job_id=job_id,
        job_status=job.status.value if hasattr(job.status, "value") else str(job.status),
    )
    if not can_access_outputs:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"Output downloads are limited to your latest {max_finished_jobs} finished jobs. This job is outside that window.",
            status_code=status.HTTP_403_FORBIDDEN
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    status_payload = get_zip_download_status_payload(current_user.id, job_id, username=current_user.username)
    if status_payload["status"] in {"queued", "processing"}:
        return JSONResponse(
            content=success_response(
                data=status_payload,
                message="ZIP generation is already in progress",
                status_code=status.HTTP_202_ACCEPTED
            ),
            status_code=status.HTTP_202_ACCEPTED
        )

    status_payload = request_job_outputs_zip_generation(job_id, current_user.id, current_user.username)

    return JSONResponse(
        content=success_response(
            data=status_payload,
            message="ZIP generation started" if status_payload["status"] != "ready" else "ZIP download link is ready",
            status_code=status.HTTP_202_ACCEPTED if status_payload["status"] != "ready" else status.HTTP_200_OK
        ),
        status_code=status.HTTP_202_ACCEPTED if status_payload["status"] != "ready" else status.HTTP_200_OK
    )


@router.get("/jobs/{job_id}/download-zip")
async def get_job_outputs_zip_download(
    job_id: int,
    current_user: UserResponse = Depends(get_current_user),
    redirect: bool = Query(False, description="Whether to redirect to the presigned ZIP URL when ready"),
):
    """
    Get the current ZIP generation status and optionally redirect when a link is ready.
    """
    job = get_job_by_id(job_id, user_id=current_user.id)
    if job is None:
        error_data = not_found_response("Job", job_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    can_access_outputs, max_finished_jobs = can_user_access_job_outputs(
        user_id=current_user.id,
        username=current_user.username,
        job_id=job_id,
        job_status=job.status.value if hasattr(job.status, "value") else str(job.status),
    )
    if not can_access_outputs:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"Output downloads are limited to your latest {max_finished_jobs} finished jobs. This job is outside that window.",
            status_code=status.HTTP_403_FORBIDDEN
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    status_payload = get_zip_download_status_payload(current_user.id, job_id, username=current_user.username)
    if redirect and status_payload["status"] == "ready" and status_payload.get("download_url"):
        return RedirectResponse(url=status_payload["download_url"], status_code=status.HTTP_302_FOUND)

    return success_response(
        data=status_payload,
        message="ZIP download status retrieved successfully"
    )


@router.delete("/files/{file_id}")
async def delete_file(
    file_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Delete a file (both database record and S3 object).
    
    Args:
        file_id: File ID to delete
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response
    """
    # Get file record first to get S3 key
    file_record = get_file_by_id(file_id, user_id=current_user.id)
    
    if file_record is None:
        error_data = not_found_response("File", file_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    try:
        # Delete from S3
        try:
            minio_client.delete_file(
                user_id=current_user.id,
                s3_key=file_record.s3_key,
                username=current_user.username
            )
        except Exception as e:
            logger.warning(f"Error deleting file from S3: {e}")
            # Continue to delete database record even if S3 deletion fails
        
        # Delete database record
        deleted = delete_file_record(file_id, current_user.id)
        
        if not deleted:
            error_data = not_found_response("File", file_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        return success_response(
            data=None,
            message="File deleted successfully"
        )
    except Exception as e:
        logger.error(f"Error deleting file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to delete file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
