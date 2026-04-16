"""
Authentication routes for CASSIE backend.

This module provides:
- User registration
- User login with JWT tokens
- Get current user status
"""

import os
import tempfile
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field

from backend.api.models.user_model import UserCreate, UserProfileUpdate, UserResponse
from backend.api.services.user_service import create_user, get_user_by_username, get_user_by_id, update_user_password, update_user_profile
from backend.api.services.pipeline_service import get_pipelines_by_user
from backend.api.services.minio_client import MinIOClient
from backend.api.services.auth_service import (
    verify_password,
    create_access_token,
    decode_access_token,
)
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    unauthorized_response,
    ErrorCode
)
from backend.api.utils.validators import validate_username, validate_email, validate_password
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["authentication"])

# Security scheme for JWT tokens
security = HTTPBearer()


# Request/Response models
class RegisterRequest(BaseModel):
    """Request model for user registration."""
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=8)


class LoginRequest(BaseModel):
    """Request model for user login."""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Response model for login."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class TokenData(BaseModel):
    """Token payload data."""
    user_id: int
    username: str


class AuthContext(BaseModel):
    """Authenticated request context for access and upload-session tokens."""
    user: UserResponse
    token_type: str = "access"
    job_id: Optional[int] = None
    expected_total_input_files: Optional[int] = None


def _resolved_avatar_url(user) -> Optional[str]:
    stored_avatar = getattr(user, "avatar_url", None)
    if not stored_avatar:
        return None

    normalized = str(stored_avatar).strip()
    if not normalized:
        return None

    if normalized.startswith(("http://", "https://", "data:", "/api/auth/profile/avatar/")):
        return normalized

    return f"/api/auth/profile/avatar/{user.id}"


def _user_response_from_model(user) -> UserResponse:
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        bucket_name=user.bucket_name,
        display_name=getattr(user, "display_name", None),
        bio=getattr(user, "bio", None),
        affiliation=getattr(user, "affiliation", None),
        job_title=getattr(user, "job_title", None),
        location=getattr(user, "location", None),
        website_url=getattr(user, "website_url", None),
        avatar_url=_resolved_avatar_url(user),
        created_at=user.created_at,
        updated_at=user.updated_at
    )


def _public_profile_payload(user) -> dict:
    return {
        "id": user.id,
        "username": user.username,
        "display_name": getattr(user, "display_name", None),
        "bio": getattr(user, "bio", None),
        "affiliation": getattr(user, "affiliation", None),
        "job_title": getattr(user, "job_title", None),
        "location": getattr(user, "location", None),
        "website_url": getattr(user, "website_url", None),
        "avatar_url": _resolved_avatar_url(user),
        "created_at": user.created_at.isoformat() if getattr(user, "created_at", None) else None,
        "updated_at": user.updated_at.isoformat() if getattr(user, "updated_at", None) else None,
    }


async def get_auth_context(
    credentials: HTTPAuthorizationCredentials = Depends(security)
) -> AuthContext:
    """
    Resolve the bearer token to a user plus any scoped upload-session claims.
    """
    token = credentials.credentials
    payload = decode_access_token(token)

    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: int = payload.get("user_id")
    username: str = payload.get("username")
    token_type = str(payload.get("token_type") or "access")

    if user_id is None or username is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token payload",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = get_user_by_id(user_id)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
            headers={"WWW-Authenticate": "Bearer"},
        )

    context = AuthContext(
        user=_user_response_from_model(user),
        token_type=token_type,
    )

    if token_type == "job_upload_session":
        context.job_id = payload.get("job_id")
        context.expected_total_input_files = payload.get("expected_total_input_files")
        if context.job_id is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid upload session token",
                headers={"WWW-Authenticate": "Bearer"},
            )

    return context


# Dependency to get current user from JWT token
async def get_current_user(
    auth_context: AuthContext = Depends(get_auth_context)
) -> UserResponse:
    """
    Dependency to get the current authenticated user from JWT token.
    
    Args:
        credentials: HTTP Bearer token credentials
        
    Returns:
        UserResponse: Current user
        
    Raises:
        HTTPException: If token is invalid or user not found
    """
    if auth_context.token_type != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="This token is not valid for general authenticated access",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return auth_context.user


# Optional dependency for routes that may or may not require auth
async def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(HTTPBearer(auto_error=False))
) -> Optional[UserResponse]:
    """
    Optional dependency to get current user if token is provided.
    
    Args:
        credentials: Optional HTTP Bearer token credentials
        
    Returns:
        UserResponse: Current user if authenticated, None otherwise
    """
    if credentials is None:
        return None
    
    try:
        auth_context = await get_auth_context(credentials)
        if auth_context.token_type != "access":
            return None
        return auth_context.user
    except HTTPException:
        return None


@router.post("/register", status_code=status.HTTP_201_CREATED)
async def register(request: RegisterRequest):
    """
    Register a new user.
    
    Args:
        request: Registration request with username, email, and password
        
    Returns:
        Success response with user data
    """
    # Validate input
    is_valid, error_msg = validate_username(request.username)
    if not is_valid:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if request.email:
        is_valid, error_msg = validate_email(request.email)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    is_valid, error_msg = validate_password(request.password)
    if not is_valid:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Generate bucket name
    bucket_name = f"cassie-user-{request.username.lower()}"
    
    # Create user
    try:
        user_data = UserCreate(
            username=request.username,
            email=request.email,
            password=request.password,
            bucket_name=bucket_name
        )
        user = create_user(user_data)
        
        user_response = _user_response_from_model(user)
        
        return success_response(
            data=user_response.model_dump(),
            message="User registered successfully",
            status_code=status.HTTP_201_CREATED
        )
        
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.CONFLICT,
            message=str(e),
            status_code=status.HTTP_409_CONFLICT
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_409_CONFLICT)
    except Exception as e:
        logger.error(f"Error registering user: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to register user",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/login")
async def login(request: LoginRequest):
    """
    Login user and return JWT token.
    
    Args:
        request: Login request with username and password
        
    Returns:
        Login response with access token and user data
    """
    # Get user by username
    user = get_user_by_username(request.username)
    if user is None:
        error_data = unauthorized_response("Invalid username or password")
        return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)
    
    # Verify password
    if not verify_password(request.password, user.password_hash):
        error_data = unauthorized_response("Invalid username or password")
        return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)
    
    # Create access token
    token_data = {
        "user_id": user.id,
        "username": user.username
    }
    access_token = create_access_token(data=token_data)
    
    user_response = _user_response_from_model(user)
    
    return success_response(
        data=LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user=user_response
        ).model_dump(),
        message="Login successful"
    )


@router.get("/status")
async def get_auth_status(current_user: UserResponse = Depends(get_current_user)):
    """
    Get current authenticated user status.
    
    Args:
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with user data
    """
    return success_response(
        data=current_user.model_dump(),
        message="User is authenticated"
    )


@router.get("/me")
async def get_current_user_info(current_user: UserResponse = Depends(get_current_user)):
    """
    Get current user information (alias for /status).
    
    Args:
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with user data
    """
    return success_response(
        data=current_user.model_dump(),
        message="User information retrieved successfully"
    )


@router.get("/profile")
async def get_profile(current_user: UserResponse = Depends(get_current_user)):
    """Return current user profile plus their shared community entries."""
    pipelines = [
        pipeline for pipeline in get_pipelines_by_user(current_user.id)
        if getattr(pipeline, "is_shared", False)
    ]
    return success_response(
        data={
            "user": current_user.model_dump(),
            "community_entries": [
                {
                    "id": pipeline.id,
                    "name": pipeline.name,
                    "description": pipeline.description,
                    "saved_at": pipeline.saved_at.isoformat() if pipeline.saved_at else None,
                    "is_shared": pipeline.is_shared,
                }
                for pipeline in pipelines
            ],
        },
        message="Profile retrieved successfully",
    )


@router.get("/profile/{user_id}")
async def get_public_profile(user_id: int):
    """Return a public, read-only user profile with their shared community entries."""
    user = get_user_by_id(user_id)
    if user is None:
        error_data = error_response(
            error_code=ErrorCode.NOT_FOUND,
            message="Profile not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    pipelines = [
        pipeline for pipeline in get_pipelines_by_user(user_id)
        if getattr(pipeline, "is_shared", False)
    ]
    return success_response(
        data={
            "user": _public_profile_payload(user),
            "community_entries": [
                {
                    "id": pipeline.id,
                    "name": pipeline.name,
                    "description": pipeline.description,
                    "saved_at": pipeline.saved_at.isoformat() if pipeline.saved_at else None,
                    "is_shared": pipeline.is_shared,
                }
                for pipeline in pipelines
            ],
            "is_public_profile": True,
        },
        message="Public profile retrieved successfully",
    )


@router.put("/profile")
async def update_profile(
    payload: UserProfileUpdate,
    current_user: UserResponse = Depends(get_current_user),
):
    """Update profile fields and optionally change password."""
    existing_user = get_user_by_id(current_user.id)
    if existing_user is None:
        error_data = unauthorized_response("User not found")
        return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)

    if payload.new_password is not None:
        if not payload.current_password:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Current password is required to set a new password",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
        if not verify_password(payload.current_password, existing_user.password_hash):
            error_data = unauthorized_response("Current password is incorrect")
            return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)
        is_valid, error_msg = validate_password(payload.new_password)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
        update_user_password(current_user.id, payload.new_password)

    updated_user = update_user_profile(current_user.id, payload) or get_user_by_id(current_user.id)
    if updated_user is None:
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to update profile",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

    return success_response(
        data=_user_response_from_model(updated_user).model_dump(),
        message="Profile updated successfully",
    )


@router.post("/profile/avatar")
async def upload_profile_avatar(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
):
    """Upload a profile avatar image and update the current user profile."""
    content_type = (file.content_type or "").lower()
    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp", "image/svg+xml"}
    if content_type not in allowed_types:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Profile pictures must be PNG, JPEG, GIF, WEBP, or SVG",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg"}:
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
        }.get(content_type, ".img")

    max_bytes = 5 * 1024 * 1024
    uploaded_size = 0
    temp_path = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as temp_file:
            temp_path = temp_file.name
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                uploaded_size += len(chunk)
                if uploaded_size > max_bytes:
                    error_data = error_response(
                        error_code=ErrorCode.VALIDATION_ERROR,
                        message="Profile pictures must be 5 MB or smaller",
                        status_code=status.HTTP_400_BAD_REQUEST,
                    )
                    return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
                temp_file.write(chunk)

        minio_client = MinIOClient()
        avatar_key = f"profile/avatars/{uuid4().hex}{suffix}"
        minio_client.upload_file(
            user_id=current_user.id,
            username=current_user.username,
            local_path=temp_path,
            s3_key=avatar_key,
            metadata={"purpose": "profile-avatar", "content_type": content_type},
        )

        updated_user = update_user_profile(
            current_user.id,
            UserProfileUpdate(avatar_url=avatar_key),
        ) or get_user_by_id(current_user.id)

        if updated_user is None:
            error_data = error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Avatar uploaded, but profile could not be updated",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

        return success_response(
            data=_user_response_from_model(updated_user).model_dump(),
            message="Profile picture updated successfully",
        )
    except Exception as e:
        logger.error(f"Error uploading profile avatar: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to upload profile picture",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
    finally:
        await file.close()
        if temp_path and os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


@router.get("/profile/avatar/{user_id}")
async def get_profile_avatar(user_id: int):
    """Resolve a stable backend avatar URL to a fresh presigned object URL."""
    user = get_user_by_id(user_id)
    if user is None or not getattr(user, "avatar_url", None):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

    stored_avatar = str(user.avatar_url).strip()
    if stored_avatar.startswith(("http://", "https://", "data:")):
        return RedirectResponse(url=stored_avatar, status_code=status.HTTP_307_TEMPORARY_REDIRECT)

    try:
        minio_client = MinIOClient()
        presigned_url = minio_client.generate_presigned_url(
            user_id=user.id,
            username=user.username,
            s3_key=stored_avatar,
            expiration=3600,
        )
        return RedirectResponse(url=presigned_url, status_code=status.HTTP_307_TEMPORARY_REDIRECT)
    except Exception as e:
        logger.error(f"Error resolving profile avatar for user {user_id}: {e}", exc_info=True)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")
