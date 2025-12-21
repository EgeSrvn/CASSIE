"""
Authentication routes for CASSIE backend.

This module provides:
- User registration
- User login with JWT tokens
- Get current user status
"""

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field
from typing import Optional

from backend.api.models.user_model import UserCreate, UserResponse
from backend.api.services.user_service import create_user, get_user_by_username, get_user_by_id
from backend.api.services.auth_service import (
    verify_password,
    create_access_token,
    decode_access_token
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


# Dependency to get current user from JWT token
async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security)
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
    
    return UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        bucket_name=user.bucket_name,
        created_at=user.created_at,
        updated_at=user.updated_at
    )


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
        return await get_current_user(credentials)
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
        
        user_response = UserResponse(
            id=user.id,
            username=user.username,
            email=user.email,
            bucket_name=user.bucket_name,
            created_at=user.created_at,
            updated_at=user.updated_at
        )
        
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
    
    user_response = UserResponse(
        id=user.id,
        username=user.username,
        email=user.email,
        bucket_name=user.bucket_name,
        created_at=user.created_at,
        updated_at=user.updated_at
    )
    
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
