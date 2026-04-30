"""
Data file management routes for CASSIE backend.

This module provides endpoints for managing files in folders.
"""

import math
import os
import re
import shutil
import socket
import tempfile
import ipaddress
from urllib.parse import parse_qs, unquote, urlparse
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query, Form, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
import requests
from typing import Optional, List
from backend.api.routes.auth import get_current_user
from backend.api.models.user_model import UserResponse
from backend.api.services.data_file_service import (
    upload_data_file_from_path,
    create_data_file_record_for_existing_object,
    build_data_s3_key,
    get_data_files_by_folder,
    get_data_file_by_id,
    make_storage_data_filename,
    prune_missing_data_file_records,
    rename_data_file,
    move_data_file,
    delete_data_file,
    copy_data_file_to_job
)
from backend.api.services.minio_client import get_minio_client
from backend.api.services.user_service import get_user_by_id
from backend.api.services.user_limit_service import validate_user_storage_capacity
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    not_found_response,
    ErrorCode
)
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/data-files", tags=["data-files"])

minio_client = get_minio_client()
MAX_CLOUD_REDIRECTS = 5
MAX_CLOUD_IMPORT_BYTES = int(os.getenv("CASSIE_MAX_CLOUD_IMPORT_BYTES", str(5 * 1024 * 1024 * 1024)))
DIRECT_UPLOAD_MULTIPART_THRESHOLD_BYTES = int(
    os.getenv("CASSIE_DIRECT_UPLOAD_MULTIPART_THRESHOLD_BYTES", str(256 * 1024 * 1024))
)
DIRECT_UPLOAD_PART_SIZE_BYTES = int(
    os.getenv("CASSIE_DIRECT_UPLOAD_PART_SIZE_BYTES", str(64 * 1024 * 1024))
)
DIRECT_UPLOAD_URL_EXPIRATION_SECONDS = 24 * 60 * 60


def _write_upload_chunk(temp_file, chunk: bytes) -> None:
    temp_file.write(chunk)


def _parse_content_length(request: Request) -> Optional[int]:
    raw_value = request.headers.get("content-length")
    if not raw_value:
        return None
    try:
        return max(int(raw_value), 0)
    except ValueError:
        return None


class DirectUploadPrepareRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    size_bytes: int = Field(..., ge=1)
    folder_id: Optional[int] = None
    file_format: Optional[str] = Field(None, max_length=50)
    content_type: Optional[str] = Field(None, max_length=255)


class DirectUploadMultipartPart(BaseModel):
    part_number: int = Field(..., ge=1)
    etag: str = Field(..., min_length=1, max_length=512)


class DirectUploadPartUrlRequest(BaseModel):
    s3_key: str = Field(..., min_length=1, max_length=500)
    upload_id: str = Field(..., min_length=1, max_length=512)
    part_number: int = Field(..., ge=1)


class DirectUploadCompleteRequest(BaseModel):
    filename: str = Field(..., min_length=1, max_length=255)
    s3_key: str = Field(..., min_length=1, max_length=500)
    size_bytes: int = Field(..., ge=1)
    folder_id: Optional[int] = None
    file_format: Optional[str] = Field(None, max_length=50)
    upload_id: Optional[str] = Field(None, min_length=1, max_length=512)
    parts: Optional[List[DirectUploadMultipartPart]] = None


class DirectUploadAbortRequest(BaseModel):
    s3_key: str = Field(..., min_length=1, max_length=500)
    upload_id: str = Field(..., min_length=1, max_length=512)


@router.post("/direct-upload/prepare", status_code=status.HTTP_200_OK)
async def prepare_direct_data_file_upload(
    payload: DirectUploadPrepareRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Create a presigned URL so the browser can upload directly to object storage."""
    try:
        filename = _safe_cloud_filename(payload.filename)

        storage_ok, storage_error = await run_in_threadpool(
            validate_user_storage_capacity,
            current_user.id,
            current_user.username,
            payload.size_bytes,
            None,
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

        await run_in_threadpool(minio_client.ensure_user_bucket, current_user.id, current_user.username)
        storage_filename = make_storage_data_filename(filename)
        s3_key = build_data_s3_key(current_user.id, storage_filename, payload.folder_id)
        if payload.size_bytes >= DIRECT_UPLOAD_MULTIPART_THRESHOLD_BYTES:
            multipart_upload = await run_in_threadpool(
                minio_client.create_multipart_upload,
                current_user.id,
                s3_key,
                current_user.username,
                payload.content_type,
                None,
            )
            part_count = max(1, math.ceil(payload.size_bytes / DIRECT_UPLOAD_PART_SIZE_BYTES))

            return success_response(
                data={
                    "upload_strategy": "multipart",
                    "upload_id": multipart_upload["upload_id"],
                    "part_size_bytes": DIRECT_UPLOAD_PART_SIZE_BYTES,
                    "part_count": part_count,
                    "s3_key": s3_key,
                    "filename": filename,
                    "expires_in": DIRECT_UPLOAD_URL_EXPIRATION_SECONDS,
                },
                message="Multipart direct upload prepared",
            )

        upload_url = await run_in_threadpool(
            minio_client.generate_presigned_url,
            current_user.id,
            s3_key,
            DIRECT_UPLOAD_URL_EXPIRATION_SECONDS,
            current_user.username,
            "PUT",
        )
        return success_response(
            data={
                "upload_strategy": "single",
                "upload_url": upload_url,
                "s3_key": s3_key,
                "filename": filename,
                "expires_in": DIRECT_UPLOAD_URL_EXPIRATION_SECONDS,
            },
            message="Direct upload URL prepared",
        )
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
        logger.error(f"Error preparing direct data upload: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to prepare direct upload",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/direct-upload/part-url", status_code=status.HTTP_200_OK)
async def create_direct_data_file_upload_part_url(
    payload: DirectUploadPartUrlRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Create a presigned URL for one multipart upload chunk."""
    try:
        expected_prefix = f"data/{current_user.id}/"
        if not payload.s3_key.startswith(expected_prefix):
            raise ValueError("Upload key does not belong to the current user")

        upload_url = await run_in_threadpool(
            minio_client.generate_presigned_upload_part_url,
            current_user.id,
            payload.s3_key,
            payload.upload_id,
            payload.part_number,
            DIRECT_UPLOAD_URL_EXPIRATION_SECONDS,
            current_user.username,
        )

        return success_response(
            data={
                "upload_url": upload_url,
                "part_number": payload.part_number,
                "expires_in": DIRECT_UPLOAD_URL_EXPIRATION_SECONDS,
            },
            message="Multipart upload part URL prepared",
        )
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
        logger.error(f"Error preparing direct upload part URL: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to prepare multipart upload part",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/direct-upload/complete", status_code=status.HTTP_201_CREATED)
async def complete_direct_data_file_upload(
    payload: DirectUploadCompleteRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Confirm direct object upload and register it in the data library."""
    try:
        expected_prefix = f"data/{current_user.id}/"
        if not payload.s3_key.startswith(expected_prefix):
            raise ValueError("Upload key does not belong to the current user")

        if payload.upload_id:
            if not payload.parts:
                raise ValueError("Multipart direct upload completion requires uploaded parts")
            try:
                await run_in_threadpool(
                    minio_client.complete_multipart_upload,
                    current_user.id,
                    payload.s3_key,
                    payload.upload_id,
                    [part.model_dump() for part in payload.parts],
                    current_user.username,
                    payload.size_bytes,
                )
            except Exception as completion_error:
                logger.warning(
                    "Multipart upload completion for '%s' failed before final verification: %s",
                    payload.s3_key,
                    completion_error,
                )

        object_info = await run_in_threadpool(
            minio_client.get_file_info,
            current_user.id,
            payload.s3_key,
            current_user.username,
        )
        if not object_info:
            raise ValueError("Storage has not confirmed this uploaded file yet")

        actual_size = int(object_info.get("size") or 0)
        if actual_size != payload.size_bytes:
            raise ValueError(
                f"Uploaded object size mismatch: expected {payload.size_bytes} bytes, storage has {actual_size} bytes"
            )

        filename = _safe_cloud_filename(payload.filename)
        file_record = await run_in_threadpool(
            create_data_file_record_for_existing_object,
            current_user.id,
            filename,
            payload.s3_key,
            payload.folder_id,
            payload.file_format,
            actual_size,
            object_info.get("etag"),
        )

        return success_response(
            data={
                "id": file_record.id,
                "filename": file_record.filename,
                "s3_key": file_record.s3_key,
                "file_type": file_record.file_type.value,
                "file_format": file_record.file_format,
                "size_bytes": file_record.size_bytes,
                "checksum": file_record.checksum,
                "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
                "created_at": file_record.created_at.isoformat() if file_record.created_at else None,
            },
            message="File uploaded successfully",
            status_code=status.HTTP_201_CREATED,
        )
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
        logger.error(f"Error completing direct data upload: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to complete direct upload",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


@router.post("/direct-upload/abort", status_code=status.HTTP_200_OK)
async def abort_direct_data_file_upload(
    payload: DirectUploadAbortRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Abort an unfinished multipart direct upload."""
    try:
        expected_prefix = f"data/{current_user.id}/"
        if not payload.s3_key.startswith(expected_prefix):
            raise ValueError("Upload key does not belong to the current user")

        await run_in_threadpool(
            minio_client.abort_multipart_upload,
            current_user.id,
            payload.s3_key,
            payload.upload_id,
            current_user.username,
        )

        return success_response(
            data={"aborted": True},
            message="Multipart upload aborted",
        )
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
        logger.error(f"Error aborting direct data upload: {e}", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to abort multipart upload",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )


class CloudImportRequest(BaseModel):
    source_url: str = Field(..., min_length=8, max_length=4096)
    filename: Optional[str] = Field(None, max_length=255)
    folder_id: Optional[int] = None
    file_format: Optional[str] = Field(None, max_length=50)


class GoogleDriveImportRequest(BaseModel):
    file_id: str = Field(..., min_length=5, max_length=512)
    access_token: str = Field(..., min_length=20, max_length=8192)
    filename: Optional[str] = Field(None, max_length=255)
    mime_type: Optional[str] = Field(None, max_length=255)
    folder_id: Optional[int] = None
    file_format: Optional[str] = Field(None, max_length=50)


def _safe_cloud_filename(value: Optional[str]) -> str:
    raw_name = (value or "").strip()
    if raw_name:
        raw_name = unquote(raw_name.split("?")[0].split("#")[0])
    filename = os.path.basename(raw_name) if raw_name else ""
    filename = re.sub(r'[\\/:*?"<>|]+', "_", filename).strip(" .")
    if not filename:
        filename = "cloud_import.dat"
    return filename[:180]


def _extract_google_drive_file_id(source_url: str) -> Optional[str]:
    parsed = urlparse(source_url)
    if parsed.hostname not in {"drive.google.com", "www.drive.google.com"}:
        return None

    query_id = parse_qs(parsed.query).get("id", [None])[0]
    if query_id:
        return query_id

    match = re.search(r"/file/d/([^/]+)", parsed.path)
    if match:
        return match.group(1)

    return None


def _normalize_cloud_download_url(source_url: str) -> tuple[str, Optional[str]]:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError("Cloud import URL must be a valid http or https link")
    _validate_public_http_url(source_url)

    google_file_id = _extract_google_drive_file_id(source_url)
    if google_file_id:
        return f"https://drive.google.com/uc?export=download&id={google_file_id}", google_file_id

    return source_url, None


def _validate_public_http_url(source_url: str) -> None:
    parsed = urlparse(source_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Cloud import URL must be a valid http or https link")

    hostname = parsed.hostname.rstrip(".").lower()
    if hostname in {"localhost"} or hostname.endswith(".localhost"):
        raise ValueError("Cloud import URL must point to a public host")

    try:
        resolved_addresses = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80), type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise ValueError("Cloud import URL host could not be resolved") from exc

    for address_info in resolved_addresses:
        ip_text = address_info[4][0]
        ip_address = ipaddress.ip_address(ip_text)
        if (
            ip_address.is_private
            or ip_address.is_loopback
            or ip_address.is_link_local
            or ip_address.is_multicast
            or ip_address.is_reserved
            or ip_address.is_unspecified
        ):
            raise ValueError("Cloud import URL must not resolve to a private or local network address")


def _safe_streaming_get(session: requests.Session, source_url: str, **kwargs) -> requests.Response:
    current_url = source_url
    for _ in range(MAX_CLOUD_REDIRECTS + 1):
        _validate_public_http_url(current_url)
        response = session.get(current_url, allow_redirects=False, **kwargs)
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("location")
            response.close()
            if not location:
                raise ValueError("Cloud import redirect did not include a target URL")
            current_url = requests.compat.urljoin(current_url, location)
            continue
        return response
    raise ValueError("Cloud import URL redirected too many times")


def _filename_from_content_disposition(value: Optional[str]) -> Optional[str]:
    if not value:
        return None

    utf8_match = re.search(r"filename\*=UTF-8''([^;]+)", value, flags=re.IGNORECASE)
    if utf8_match:
        return unquote(utf8_match.group(1).strip().strip('"'))

    regular_match = re.search(r'filename="?([^";]+)"?', value, flags=re.IGNORECASE)
    if regular_match:
        return regular_match.group(1).strip()

    return None


def _declared_content_length(response: requests.Response) -> Optional[int]:
    value = response.headers.get("content-length")
    if not value:
        return None
    try:
        return max(int(value), 0)
    except ValueError:
        return None


def _google_confirm_token(cookies: requests.cookies.RequestsCookieJar) -> Optional[str]:
    for key, value in cookies.items():
        if key.startswith("download_warning"):
            return value
    return None


def _download_cloud_file(source_url: str, requested_filename: Optional[str]) -> tuple[str, str]:
    download_url, google_file_id = _normalize_cloud_download_url(source_url)
    session = requests.Session()
    response: Optional[requests.Response] = None
    temp_path: Optional[str] = None

    try:
        response = _safe_streaming_get(session, download_url, stream=True, timeout=(15, 120))
        response.raise_for_status()
        declared_size = _declared_content_length(response)
        if declared_size is not None and declared_size > MAX_CLOUD_IMPORT_BYTES:
            raise ValueError("Cloud file is larger than the maximum import size")

        confirm_token = _google_confirm_token(response.cookies)
        content_disposition = response.headers.get("content-disposition")
        content_type = response.headers.get("content-type", "").lower()
        if google_file_id and not confirm_token and not content_disposition and "text/html" in content_type:
            html = response.text
            token_match = re.search(r"confirm=([0-9A-Za-z_%-]+)", html)
            confirm_token = unquote(token_match.group(1)) if token_match else None
            response.close()
            if not confirm_token:
                raise ValueError("Google Drive did not return a downloadable file. Make sure link sharing is enabled for the file.")

        if google_file_id and confirm_token:
            response.close()
            response = _safe_streaming_get(
                session,
                "https://drive.google.com/uc",
                params={"export": "download", "id": google_file_id, "confirm": confirm_token},
                stream=True,
                timeout=(15, 120),
            )
            response.raise_for_status()
            declared_size = _declared_content_length(response)
            if declared_size is not None and declared_size > MAX_CLOUD_IMPORT_BYTES:
                raise ValueError("Cloud file is larger than the maximum import size")

        fallback_name = os.path.basename(urlparse(response.url).path)
        detected_name = (
            requested_filename
            or _filename_from_content_disposition(response.headers.get("content-disposition"))
            or fallback_name
        )
        filename = _safe_cloud_filename(detected_name)

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
            temp_path = temp_file.name
            downloaded_size = 0
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded_size += len(chunk)
                if downloaded_size > MAX_CLOUD_IMPORT_BYTES:
                    raise ValueError("Cloud file is larger than the maximum import size")
                temp_file.write(chunk)

        if downloaded_size <= 0:
            raise ValueError("The cloud link did not return any file content")

        return temp_path, filename
    except Exception:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise
    finally:
        if response is not None:
            response.close()


def _download_google_drive_file(
    file_id: str,
    access_token: str,
    requested_filename: Optional[str],
    selected_mime_type: Optional[str],
) -> tuple[str, str]:
    headers = {"Authorization": f"Bearer {access_token}"}
    metadata_response: Optional[requests.Response] = None
    download_response: Optional[requests.Response] = None
    temp_path: Optional[str] = None

    try:
        metadata_response = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={
                "fields": "id,name,mimeType,size,capabilities/canDownload",
                "supportsAllDrives": "true",
            },
            headers=headers,
            timeout=(15, 60),
        )
        metadata_response.raise_for_status()
        metadata = metadata_response.json()
        declared_size = metadata.get("size")
        if declared_size is not None:
            try:
                parsed_size = int(declared_size)
            except (TypeError, ValueError):
                parsed_size = 0
            if parsed_size > MAX_CLOUD_IMPORT_BYTES:
                raise ValueError("Google Drive file is larger than the maximum import size")
        drive_mime_type = metadata.get("mimeType") or selected_mime_type or ""
        if str(drive_mime_type).startswith("application/vnd.google-apps."):
            raise ValueError("Google Workspace documents must be exported from Drive before importing into CASSIE.")
        if metadata.get("capabilities") and metadata["capabilities"].get("canDownload") is False:
            raise ValueError("Google Drive says this file cannot be downloaded by the current account.")

        filename = _safe_cloud_filename(requested_filename or metadata.get("name") or file_id)

        download_response = requests.get(
            f"https://www.googleapis.com/drive/v3/files/{file_id}",
            params={"alt": "media", "supportsAllDrives": "true"},
            headers=headers,
            stream=True,
            timeout=(15, 120),
        )
        download_response.raise_for_status()
        response_size = _declared_content_length(download_response)
        if response_size is not None and response_size > MAX_CLOUD_IMPORT_BYTES:
            raise ValueError("Google Drive file is larger than the maximum import size")

        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(filename)[1]) as temp_file:
            temp_path = temp_file.name
            downloaded_size = 0
            for chunk in download_response.iter_content(chunk_size=1024 * 1024):
                if not chunk:
                    continue
                downloaded_size += len(chunk)
                if downloaded_size > MAX_CLOUD_IMPORT_BYTES:
                    raise ValueError("Google Drive file is larger than the maximum import size")
                temp_file.write(chunk)

        if downloaded_size <= 0:
            raise ValueError("Google Drive did not return any file content")

        return temp_path, filename
    except Exception:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError:
                pass
        raise
    finally:
        if metadata_response is not None:
            metadata_response.close()
        if download_response is not None:
            download_response.close()


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_data_file_endpoint(
    request: Request,
    file: UploadFile = File(...),
    folder_id: Optional[str] = Form(None, description="Target folder ID (None for root)"),
    file_format: Optional[str] = Form(None, description="File format (fastq, fasta, etc.)"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Upload a file to a folder.
    
    Args:
        file: Uploaded file
        folder_id: Target folder ID (None for root)
        file_format: Optional file format
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Created file record
    """
    temp_path: Optional[str] = None
    try:
        upload_filename = _safe_cloud_filename(file.filename)
        request_size = _parse_content_length(request)
        if request_size is not None:
            storage_ok, storage_error = await run_in_threadpool(
                validate_user_storage_capacity,
                current_user.id,
                current_user.username,
                request_size,
                shutil.disk_usage(tempfile.gettempdir()).free,
            )
            if not storage_ok:
                raise ValueError(storage_error)

        folder_id_int = None
        if folder_id and folder_id.strip():
            try:
                folder_id_int = int(folder_id)
            except ValueError:
                raise ValueError(f"Invalid folder_id: {folder_id}")

        file_size = 0
        chunk_size = 1024 * 1024
        with tempfile.NamedTemporaryFile(delete=False, suffix=os.path.splitext(upload_filename)[1]) as temp_file:
            temp_path = temp_file.name
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break
                file_size += len(chunk)
                await run_in_threadpool(_write_upload_chunk, temp_file, chunk)
            await run_in_threadpool(temp_file.flush)

        if file_size <= 0:
            raise ValueError("Uploaded file is empty")

        file_record = await run_in_threadpool(
            upload_data_file_from_path,
            user_id=current_user.id,
            local_path=temp_path,
            filename=upload_filename,
            folder_id=folder_id_int,
            file_format=file_format,
        )
        
        return success_response(
            data={
                "id": file_record.id,
                "filename": file_record.filename,
                "s3_key": file_record.s3_key,
                "file_type": file_record.file_type.value,
                "file_format": file_record.file_format,
                "size_bytes": file_record.size_bytes,
                "checksum": file_record.checksum,
                "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
                "created_at": file_record.created_at.isoformat() if file_record.created_at else None
            },
            message="File uploaded successfully",
            status_code=status.HTTP_201_CREATED
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error uploading data file: {e}", exc_info=True)
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
            except OSError as cleanup_error:
                logger.warning(f"Failed to delete upload temp file {temp_path}: {cleanup_error}")


@router.post("/import-cloud", status_code=status.HTTP_201_CREATED)
async def import_cloud_data_file_endpoint(
    payload: CloudImportRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Import a public cloud-hosted file into the user's data library.

    Google Drive share links and direct HTTP(S) file URLs are supported.
    """
    temp_path: Optional[str] = None
    try:
        temp_path, filename = await run_in_threadpool(
            _download_cloud_file,
            payload.source_url,
            payload.filename,
        )

        file_record = await run_in_threadpool(
            upload_data_file_from_path,
            user_id=current_user.id,
            local_path=temp_path,
            filename=filename,
            folder_id=payload.folder_id,
            file_format=payload.file_format,
        )

        return success_response(
            data={
                "id": file_record.id,
                "filename": file_record.filename,
                "s3_key": file_record.s3_key,
                "file_type": file_record.file_type.value,
                "file_format": file_record.file_format,
                "size_bytes": file_record.size_bytes,
                "checksum": file_record.checksum,
                "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
                "created_at": file_record.created_at.isoformat() if file_record.created_at else None
            },
            message="Cloud file imported successfully",
            status_code=status.HTTP_201_CREATED
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except requests.RequestException as e:
        logger.error(f"Error importing cloud data file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Could not download the cloud file. Make sure the link is public or directly downloadable.",
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error importing cloud data file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to import cloud file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError as cleanup_error:
                logger.warning(f"Failed to delete cloud import temp file {temp_path}: {cleanup_error}")


@router.post("/import-google-drive", status_code=status.HTTP_201_CREATED)
async def import_google_drive_data_file_endpoint(
    payload: GoogleDriveImportRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Import a file selected through Google Drive Picker into the user's data library.
    """
    temp_path: Optional[str] = None
    try:
        temp_path, filename = await run_in_threadpool(
            _download_google_drive_file,
            payload.file_id,
            payload.access_token,
            payload.filename,
            payload.mime_type,
        )

        file_record = await run_in_threadpool(
            upload_data_file_from_path,
            user_id=current_user.id,
            local_path=temp_path,
            filename=filename,
            folder_id=payload.folder_id,
            file_format=payload.file_format,
        )

        return success_response(
            data={
                "id": file_record.id,
                "filename": file_record.filename,
                "s3_key": file_record.s3_key,
                "file_type": file_record.file_type.value,
                "file_format": file_record.file_format,
                "size_bytes": file_record.size_bytes,
                "checksum": file_record.checksum,
                "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
                "created_at": file_record.created_at.isoformat() if file_record.created_at else None
            },
            message="Google Drive file imported successfully",
            status_code=status.HTTP_201_CREATED
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except requests.RequestException as e:
        logger.error(f"Error importing Google Drive file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Could not download the Google Drive file. Make sure your Google account can download it.",
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error importing Google Drive file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to import Google Drive file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except OSError as cleanup_error:
                logger.warning(f"Failed to delete Google Drive import temp file {temp_path}: {cleanup_error}")


@router.get("", response_model=dict)
async def list_data_files(
    folder_id: Optional[int] = Query(None, description="Filter by folder ID"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List files in a folder.
    
    Args:
        folder_id: Optional folder ID filter (None for root)
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: List of files
    """
    try:
        await run_in_threadpool(
            prune_missing_data_file_records,
            current_user.id,
            current_user.username,
        )
        files = get_data_files_by_folder(folder_id, current_user.id)
        return success_response(
            data=[{
                "id": f.id,
                "filename": f.filename,
                "s3_key": f.s3_key,
                "file_type": f.file_type.value,
                "file_format": f.file_format,
                "size_bytes": f.size_bytes,
                "checksum": f.checksum,
                "uploaded_at": f.uploaded_at.isoformat() if f.uploaded_at else None,
                "created_at": f.created_at.isoformat() if f.created_at else None
            } for f in files],
            message="Files retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error listing data files: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve files",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/tree", response_model=dict)
async def get_data_file_tree(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get folder tree with files.
    
    Args:
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Folder tree with files
    """
    try:
        from backend.api.services.folder_service import get_folder_tree
        await run_in_threadpool(
            prune_missing_data_file_records,
            current_user.id,
            current_user.username,
        )
        tree = get_folder_tree(current_user.id)
        return success_response(
            data=tree,
            message="File tree retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error getting file tree: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve file tree",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{file_id}", response_model=dict)
async def get_data_file(
    file_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get file by ID.
    
    Args:
        file_id: File ID
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: File details
    """
    file_record = get_data_file_by_id(file_id, current_user.id)
    
    if not file_record:
        error_data = not_found_response("File", file_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    return success_response(
        data={
            "id": file_record.id,
            "filename": file_record.filename,
            "s3_key": file_record.s3_key,
            "file_type": file_record.file_type.value,
            "file_format": file_record.file_format,
            "size_bytes": file_record.size_bytes,
            "checksum": file_record.checksum,
            "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
            "created_at": file_record.created_at.isoformat() if file_record.created_at else None
        },
        message="File retrieved successfully"
    )


@router.put("/{file_id}/rename", response_model=dict)
async def rename_data_file_endpoint(
    file_id: int,
    new_name: str = Query(..., description="New filename"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Rename a file.
    
    Args:
        file_id: File ID
        new_name: New filename
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Updated file
    """
    try:
        file_record = rename_data_file(file_id, current_user.id, new_name)
        
        if not file_record:
            error_data = not_found_response("File", file_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        return success_response(
            data={
                "id": file_record.id,
                "filename": file_record.filename,
                "s3_key": file_record.s3_key,
                "file_type": file_record.file_type.value,
                "file_format": file_record.file_format,
                "size_bytes": file_record.size_bytes,
                "checksum": file_record.checksum,
                "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
                "created_at": file_record.created_at.isoformat() if file_record.created_at else None
            },
            message="File renamed successfully"
        )
    except Exception as e:
        logger.error(f"Error renaming data file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to rename file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/{file_id}/move", response_model=dict)
async def move_data_file_endpoint(
    file_id: int,
    target_folder_id: Optional[int] = Query(None, description="Target folder ID (None for root)"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Move a file to a different folder.
    
    Args:
        file_id: File ID
        target_folder_id: Target folder ID (None for root)
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Updated file
    """
    try:
        file_record = move_data_file(file_id, current_user.id, target_folder_id)
        
        if not file_record:
            error_data = not_found_response("File", file_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        return success_response(
            data={
                "id": file_record.id,
                "filename": file_record.filename,
                "s3_key": file_record.s3_key,
                "file_type": file_record.file_type.value,
                "file_format": file_record.file_format,
                "size_bytes": file_record.size_bytes,
                "checksum": file_record.checksum,
                "uploaded_at": file_record.uploaded_at.isoformat() if file_record.uploaded_at else None,
                "created_at": file_record.created_at.isoformat() if file_record.created_at else None
            },
            message="File moved successfully"
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error moving data file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to move file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_data_file_endpoint(
    file_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Delete a file.
    
    Args:
        file_id: File ID
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Success or error response
    """
    try:
        deleted = delete_data_file(file_id, current_user.id)
        
        if not deleted:
            error_data = not_found_response("File", file_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        return JSONResponse(
            content={"message": "File deleted successfully"},
            status_code=status.HTTP_204_NO_CONTENT
        )
    except Exception as e:
        logger.error(f"Error deleting data file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to delete file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{file_id}/download")
async def download_data_file(
    file_id: int,
    current_user: UserResponse = Depends(get_current_user),
    redirect: bool = Query(True, description="Whether to redirect to presigned URL or return JSON")
):
    """
    Download a file.
    
    Args:
        file_id: File ID
        current_user: Current authenticated user
        redirect: If True, redirects to presigned URL. If False, returns JSON with URL.
        
    Returns:
        RedirectResponse or JSONResponse: Presigned URL or redirect
    """
    try:
        file_record = get_data_file_by_id(file_id, current_user.id)
        
        if not file_record:
            error_data = not_found_response("File", file_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        # Get user for bucket name
        user = get_user_by_id(current_user.id)
        if not user:
            error_data = error_response(
                error_code=ErrorCode.NOT_FOUND,
                message="User not found",
                status_code=status.HTTP_404_NOT_FOUND
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        # Generate presigned URL for download
        try:
            presigned_url = minio_client.generate_presigned_url(
                user_id=current_user.id,
                s3_key=file_record.s3_key,
                username=user.username,
                expiration=3600  # 1 hour
            )
            
            # If redirect is False, return JSON with URL
            if not redirect:
                return success_response(
                    data={
                        "download_url": presigned_url,
                        "filename": file_record.filename
                    },
                    message="Download URL generated successfully"
                )
            
            # Redirect to presigned URL
            from fastapi.responses import RedirectResponse
            return RedirectResponse(url=presigned_url, status_code=status.HTTP_302_FOUND)
            
        except Exception as e:
            logger.error(f"Error generating presigned URL: {e}", exc_info=True)
            error_data = error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Failed to generate download URL",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
            
    except Exception as e:
        logger.error(f"Error downloading data file: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to download file",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
