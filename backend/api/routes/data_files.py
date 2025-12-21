"""
Data file management routes for CASSIE backend.

This module provides endpoints for managing files in folders.
"""

import os
from fastapi import APIRouter, Depends, UploadFile, File, HTTPException, status, Query, Form
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional
from backend.api.routes.auth import get_current_user
from backend.api.models.user_model import UserResponse
from backend.api.services.data_file_service import (
    upload_data_file,
    get_data_files_by_folder,
    get_data_file_by_id,
    rename_data_file,
    move_data_file,
    delete_data_file,
    copy_data_file_to_job
)
from backend.api.services.minio_client import get_minio_client
from backend.api.services.user_service import get_user_by_id
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


@router.post("/upload", status_code=status.HTTP_201_CREATED)
async def upload_data_file_endpoint(
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
    try:
        # Read file content
        content = await file.read()
        
        # Parse folder_id from form data (can be string or None)
        folder_id_int = None
        if folder_id and folder_id.strip():
            try:
                folder_id_int = int(folder_id)
            except ValueError:
                raise ValueError(f"Invalid folder_id: {folder_id}")
        
        # Upload file
        file_record = upload_data_file(
            user_id=current_user.id,
            file_content=content,
            filename=file.filename,
            folder_id=folder_id_int,
            file_format=file_format
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

