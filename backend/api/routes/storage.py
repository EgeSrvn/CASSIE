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
import tempfile
import hashlib
import time
import zipfile
import urllib.parse
from threading import Lock
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query, BackgroundTasks
from fastapi.responses import JSONResponse, StreamingResponse, RedirectResponse
from typing import Optional, List, Dict, Any, Tuple
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
    get_file_by_id,
    get_files_by_user,
    update_file,
    delete_file_record,
    count_files_by_user
)
from backend.api.services.minio_client import MinIOClient, get_minio_client
from backend.api.services.job_service import get_job_by_id
from backend.api.models.job_model import JobStatus
from backend.api.services.job_launch_service import (
    get_auto_start_payload,
    start_job_execution_task,
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

logger = get_logger(__name__)

router = APIRouter(prefix="/storage", tags=["storage"])

# Initialize MinIO client
minio_client = get_minio_client()
ZIP_DOWNLOAD_EXPIRATION_SECONDS = 3600
zip_download_jobs: Dict[Tuple[int, int], Dict[str, Any]] = {}
zip_download_jobs_lock = Lock()


def _get_zip_job_key(user_id: int, job_id: int) -> Tuple[int, int]:
    return (user_id, job_id)


def _get_zip_download_status_payload(user_id: int, job_id: int) -> Dict[str, Any]:
    job_key = _get_zip_job_key(user_id, job_id)
    with zip_download_jobs_lock:
        status_data = zip_download_jobs.get(job_key)
        if not status_data:
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
            payload.update({
                "status": "expired",
                "download_url": None,
                "error": "Download link expired. Generate a new ZIP link to continue.",
            })
            zip_download_jobs[job_key] = payload

        if payload.get("status") != "ready":
            payload["download_url"] = None

        return payload


def _set_zip_download_status(user_id: int, job_id: int, **values: Any) -> None:
    job_key = _get_zip_job_key(user_id, job_id)
    with zip_download_jobs_lock:
        current = zip_download_jobs.get(job_key, {})
        current.update(values)
        current["updated_at"] = time.time()
        zip_download_jobs[job_key] = current


def _build_job_outputs_zip_for_download(job_id: int, current_user: UserResponse) -> Dict[str, Any]:
    job = get_job_by_id(job_id, user_id=current_user.id)
    if job is None:
        raise FileNotFoundError(f"Job {job_id} not found")

    output_files = get_files_by_user(
        user_id=current_user.id,
        job_id=job_id,
        file_type=FileType.OUTPUT,
        limit=1000,
        offset=0
    )

    if not output_files:
        raise ValueError("No output files found for this job")

    temp_zip = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    temp_zip_path = temp_zip.name
    temp_zip.close()

    added_files = 0

    try:
        with zipfile.ZipFile(temp_zip_path, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            for file_record in output_files:
                try:
                    temp_file = tempfile.NamedTemporaryFile(delete=False)
                    temp_path = temp_file.name
                    temp_file.close()

                    try:
                        minio_client.download_file(
                            user_id=current_user.id,
                            s3_key=file_record.s3_key,
                            local_path=temp_path,
                            username=current_user.username
                        )
                        zip_file.write(temp_path, file_record.filename)
                        added_files += 1
                        logger.info(f"Added {file_record.filename} to ZIP archive")
                    finally:
                        if os.path.exists(temp_path):
                            try:
                                os.unlink(temp_path)
                            except Exception as e:
                                logger.warning(f"Failed to delete temp file {temp_path}: {e}")
                except Exception as e:
                    logger.warning(f"Failed to add {file_record.filename} to ZIP: {e}")
                    continue

        if added_files == 0:
            raise RuntimeError("Failed to create ZIP archive because no output files could be packaged")

        job_name_safe = "".join(c for c in job.name if c.isalnum() or c in (' ', '-', '_')).rstrip()
        zip_filename = f"job_{job_id}_{job_name_safe}_outputs.zip"
        safe_job_fragment = "".join(c if c.isalnum() or c in ('-', '_') else "_" for c in job.name).strip("_") or f"job_{job_id}"
        zip_s3_key = f"generated-archives/jobs/{job_id}/{safe_job_fragment}_outputs.zip"

        minio_client.upload_file(
            user_id=current_user.id,
            local_path=temp_zip_path,
            s3_key=zip_s3_key,
            username=current_user.username,
            metadata={
                "job-id": str(job_id),
                "archive-type": "job-outputs-zip"
            }
        )

        content_disposition = (
            f'attachment; filename="{zip_filename}"; '
            f"filename*=UTF-8''{urllib.parse.quote(zip_filename, safe='')}"
        )
        download_url = minio_client.generate_presigned_url(
            user_id=current_user.id,
            s3_key=zip_s3_key,
            username=current_user.username,
            expiration=ZIP_DOWNLOAD_EXPIRATION_SECONDS,
            response_content_disposition=content_disposition
        )

        return {
            "status": "ready",
            "download_url": download_url,
            "filename": zip_filename,
            "expires_in": ZIP_DOWNLOAD_EXPIRATION_SECONDS,
            "expires_at": time.time() + ZIP_DOWNLOAD_EXPIRATION_SECONDS,
            "error": None,
        }
    finally:
        if os.path.exists(temp_zip_path):
            try:
                os.unlink(temp_zip_path)
            except Exception as e:
                logger.warning(f"Failed to delete temp ZIP file {temp_zip_path}: {e}")


def _generate_job_outputs_zip_in_background(job_id: int, current_user: UserResponse) -> None:
    try:
        _set_zip_download_status(
            current_user.id,
            job_id,
            status="processing",
            download_url=None,
            filename=None,
            expires_in=None,
            expires_at=None,
            error=None,
        )
        result = _build_job_outputs_zip_for_download(job_id, current_user)
        _set_zip_download_status(current_user.id, job_id, **result)
    except Exception as e:
        logger.error(f"Error creating ZIP archive for job {job_id}: {e}", exc_info=True)
        _set_zip_download_status(
            current_user.id,
            job_id,
            status="failed",
            download_url=None,
            expires_in=None,
            expires_at=None,
            error=str(e) or "Failed to create ZIP archive",
        )


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_file(
    file: UploadFile = File(...),
    job_id: Optional[int] = Query(None, description="Job ID to associate file with (optional for pre-upload)"),
    file_type: FileType = Query(..., description="Type of file (input, output, intermediate, log)"),
    file_format: Optional[str] = Query(None, description="File format (fastq, fasta, etc.)"),
    background_tasks: BackgroundTasks = BackgroundTasks(),
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
    temp_file = None
    try:
        # Create temporary file
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(file.filename)[1]) as temp_file:
            temp_path = temp_file.name
            
            # Write uploaded content to temp file
            content = await file.read()
            temp_file.write(content)
            temp_file.flush()
            
            # Calculate file size and checksum
            file_size = len(content)
            hash_md5 = hashlib.md5()
            hash_md5.update(content)
            checksum = hash_md5.hexdigest()
            
            # Generate S3 key (path within user's bucket)
            if job_id:
                s3_key = f"jobs/{job_id}/{file_type.value}/{file.filename}"
            else:
                # Store in staging area for later job association
                s3_key = f"staging/{current_user.id}/{int(time.time())}_{file.filename}"
            
            # Ensure user bucket exists
            minio_client.ensure_user_bucket(user_id=current_user.id, username=current_user.username)
            
            # Upload to MinIO/S3
            upload_result = minio_client.upload_file(
                user_id=current_user.id,
                local_path=temp_path,
                s3_key=s3_key,
                username=current_user.username
            )
            
            # Create file record in database (job_id can be None for staging)
            file_data = FileCreate(
                job_id=job_id,  # Can be None for pre-upload
                filename=file.filename,
                s3_key=s3_key,
                file_type=file_type,
                file_format=file_format,
                size_bytes=file_size,
                checksum=checksum
            )
            
            file_record = create_file_record(file_data)
            
            if job_id and file_type == FileType.INPUT:
                try:
                    expected_total_input_files = auth_context.expected_total_input_files
                    if expected_total_input_files:
                        current_job_input_files = get_files_by_user(
                            user_id=current_user.id,
                            job_id=job_id,
                            file_type=FileType.INPUT,
                            limit=expected_total_input_files + 5,
                            offset=0,
                        )
                        current_input_count = len(current_job_input_files)
                        if current_input_count < expected_total_input_files:
                            logger.info(
                                f"Input file uploaded to pending job {job_id}, but waiting for more files before auto-start. "
                                f"Currently have {current_input_count}/{expected_total_input_files} input file(s)."
                            )
                            ready_job = None
                            input_file_ids = None
                            readiness_error = (
                                f"Waiting for all queued uploads ({current_input_count}/{expected_total_input_files} received)"
                            )
                        else:
                            ready_job, input_file_ids, readiness_error = get_auto_start_payload(job_id, current_user.id)
                    else:
                        ready_job, input_file_ids, readiness_error = get_auto_start_payload(job_id, current_user.id)

                    if ready_job and input_file_ids:
                        background_tasks.add_task(
                            start_job_execution_task,
                            ready_job.id,
                            current_user.id,
                            ready_job.workflow_id,
                            input_file_ids,
                        )
                        logger.info(
                            f"Input file uploaded to pending job {job_id}. "
                            f"Found {len(input_file_ids)} input file(s). Job will start automatically."
                        )
                    elif readiness_error:
                        logger.info(f"Job {job_id} not auto-started after upload: {readiness_error}")
                except Exception as pipeline_error:
                    # Don't fail file upload if pipeline start fails
                    logger.warning(
                        f"Failed to start pipeline for job {job_id} after file upload: {pipeline_error}",
                        exc_info=True
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
        # Clean up temporary file
        if temp_file and os.path.exists(temp_path):
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
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user),
):
    """
    Start background generation of a ZIP archive for all job outputs.
    """
    job = get_job_by_id(job_id, user_id=current_user.id)
    if job is None:
        error_data = not_found_response("Job", job_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    status_payload = _get_zip_download_status_payload(current_user.id, job_id)
    if status_payload["status"] in {"queued", "processing"}:
        return JSONResponse(
            content=success_response(
                data=status_payload,
                message="ZIP generation is already in progress",
                status_code=status.HTTP_202_ACCEPTED
            ),
            status_code=status.HTTP_202_ACCEPTED
        )

    _set_zip_download_status(
        current_user.id,
        job_id,
        status="queued",
        download_url=None,
        filename=None,
        expires_in=None,
        expires_at=None,
        error=None,
    )
    background_tasks.add_task(_generate_job_outputs_zip_in_background, job_id, current_user)

    return JSONResponse(
        content=success_response(
            data=_get_zip_download_status_payload(current_user.id, job_id),
            message="ZIP generation started",
            status_code=status.HTTP_202_ACCEPTED
        ),
        status_code=status.HTTP_202_ACCEPTED
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

    status_payload = _get_zip_download_status_payload(current_user.id, job_id)
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
