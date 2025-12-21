"""
Folder management routes for CASSIE backend.

This module provides endpoints for folder CRUD operations.
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query
from fastapi.responses import JSONResponse
from typing import Optional, List
from backend.api.routes.auth import get_current_user
from backend.api.models.user_model import UserResponse
from backend.api.models.folder_model import (
    FolderCreate,
    FolderUpdate,
    FolderResponse
)
from backend.api.services.folder_service import (
    create_folder,
    get_folder_by_id,
    get_folders_by_user,
    get_folder_tree,
    update_folder,
    delete_folder
)
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    not_found_response,
    ErrorCode
)
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/folders", tags=["folders"])


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_folder_endpoint(
    folder_data: FolderCreate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create a new folder.
    
    Args:
        folder_data: Folder creation data
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Created folder
    """
    try:
        folder = create_folder(current_user.id, folder_data)
        return success_response(
            data=FolderResponse.model_validate(folder).model_dump(),
            message="Folder created successfully",
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
        logger.error(f"Error creating folder: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to create folder",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("", response_model=dict)
async def list_folders(
    parent_id: Optional[int] = Query(None, description="Filter by parent folder ID"),
    tree: bool = Query(False, description="Return as tree structure"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List user's folders.
    
    Args:
        parent_id: Optional parent folder ID filter
        tree: If True, return nested tree structure with files
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: List of folders or tree structure
    """
    try:
        if tree:
            folders = get_folder_tree(current_user.id)
            return success_response(
                data=folders,
                message="Folder tree retrieved successfully"
            )
        else:
            folders = get_folders_by_user(current_user.id, parent_id)
            return success_response(
                data=[FolderResponse.model_validate(f).model_dump() for f in folders],
                message="Folders retrieved successfully"
            )
    except Exception as e:
        logger.error(f"Error listing folders: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve folders",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{folder_id}", response_model=dict)
async def get_folder(
    folder_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get folder by ID.
    
    Args:
        folder_id: Folder ID
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Folder details
    """
    folder = get_folder_by_id(folder_id, current_user.id)
    
    if not folder:
        error_data = not_found_response("Folder", folder_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    return success_response(
        data=FolderResponse.model_validate(folder).model_dump(),
        message="Folder retrieved successfully"
    )


@router.put("/{folder_id}", response_model=dict)
async def update_folder_endpoint(
    folder_id: int,
    folder_data: FolderUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Update a folder (rename or move).
    
    Args:
        folder_id: Folder ID
        folder_data: Folder update data
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Updated folder
    """
    try:
        folder = update_folder(folder_id, current_user.id, folder_data)
        
        if not folder:
            error_data = not_found_response("Folder", folder_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        return success_response(
            data=FolderResponse.model_validate(folder).model_dump(),
            message="Folder updated successfully"
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error updating folder: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to update folder",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.delete("/{folder_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_folder_endpoint(
    folder_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Delete a folder and all its contents.
    
    Args:
        folder_id: Folder ID
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Success or error response
    """
    try:
        deleted = delete_folder(folder_id, current_user.id)
        
        if not deleted:
            error_data = not_found_response("Folder", folder_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        return JSONResponse(
            content={"message": "Folder deleted successfully"},
            status_code=status.HTTP_204_NO_CONTENT
        )
    except Exception as e:
        logger.error(f"Error deleting folder: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to delete folder",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

