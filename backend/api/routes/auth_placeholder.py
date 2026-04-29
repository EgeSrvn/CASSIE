"""
Placeholder authentication for development and testing.

This module provides a simple header-based authentication that can be used
before full JWT authentication is implemented or when testing.

Usage:
    from backend.api.routes.auth_placeholder import get_current_user_placeholder
    
    @router.get("/jobs")
    async def list_jobs(current_user: UserResponse = Depends(get_current_user_placeholder)):
        ...
"""

import os
from fastapi import Header, HTTPException, status
from typing import Optional
from backend.api.models.user_model import UserResponse
from backend.api.services.user_service import get_user_by_id
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


async def get_current_user_placeholder(
    x_user_id: Optional[int] = Header(None, alias="X-User-ID", description="User ID for placeholder auth")
) -> UserResponse:
    """
    Placeholder dependency to get current user from X-User-ID header.
    
    This is a temporary solution for development/testing before full JWT auth is working.
    
    Args:
        x_user_id: User ID from X-User-ID header
        
    Returns:
        UserResponse: Current user
        
    Raises:
        HTTPException: If user_id not provided or user not found
    """
    if os.getenv("CASSIE_ENABLE_PLACEHOLDER_AUTH", "false").lower() not in {"1", "true", "yes"}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Placeholder authentication is disabled",
        )

    if x_user_id is None:
        # Default to user_id=1 for testing if header not provided
        logger.warning("X-User-ID header not provided, using default user_id=1 for testing")
        x_user_id = 1
    
    user = get_user_by_id(x_user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"User with id {x_user_id} not found"
        )
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        bucket_name=user.bucket_name,
        created_at=user.created_at,
        updated_at=user.updated_at
    )
