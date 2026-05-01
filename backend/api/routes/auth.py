"""
Authentication routes for CASSIE backend.

This module provides:
- User registration
- User login with JWT tokens
- Get current user status
"""

import os
import secrets
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Optional
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, status
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel, EmailStr, Field

from backend.api.models.user_model import UserCreate, UserProfileUpdate, UserResponse
from backend.api.services.user_service import (
    clear_account_deletion_code,
    clear_login_two_factor_code,
    clear_password_reset_code,
    create_user,
    delete_user_account,
    get_account_deletion_code_state,
    get_user_by_email,
    get_user_by_id,
    get_user_by_username,
    purge_expired_unverified_users,
    reset_email_security_preferences,
    set_account_deletion_code,
    set_email_verification_code,
    set_login_two_factor_code,
    set_password_reset_code,
    update_user_password,
    update_user_profile,
    verify_user_email,
)
from backend.api.services.pipeline_service import get_pipelines_by_user
from backend.api.services.minio_client import MinIOClient
from backend.api.services.auth_service import (
    verify_password,
    create_access_token,
    decode_access_token,
)
from backend.api.services.billing_service import deposit_user_cash
from backend.api.services.email_service import send_email
from backend.api.services.invitation_code_service import (
    attach_invitation_code_to_user,
    claim_invitation_code,
    normalize_invitation_code,
    release_invitation_code,
)
from backend.api.services.user_notification_service import build_login_two_factor_email
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
CODE_EXPIRY_MINUTES = 15
EMAIL_RESEND_COOLDOWN_SECONDS = 120
GENERIC_VERIFICATION_MESSAGE = "If an account needs verification, a code will be sent to its email address."
GENERIC_PASSWORD_RESET_MESSAGE = "If an account exists for that email address, a password reset code will be sent."

# Security scheme for JWT tokens
security = HTTPBearer()


# Request/Response models
class RegisterRequest(BaseModel):
    """Request model for user registration."""
    username: str = Field(..., min_length=3, max_length=50)
    email: Optional[EmailStr] = None
    password: str = Field(..., min_length=8)
    invitation_code: str = Field(..., min_length=1, max_length=80)


class LoginRequest(BaseModel):
    """Request model for user login."""
    username: str = Field(..., min_length=1)
    password: str = Field(..., min_length=1)


class LoginResponse(BaseModel):
    """Response model for login."""
    access_token: str
    token_type: str = "bearer"
    user: UserResponse


class LoginTwoFactorChallengeResponse(BaseModel):
    username: str
    email: EmailStr
    two_factor_required: bool = True
    verification_preview_code: Optional[str] = None
    expires_in_minutes: int


class VerificationChallengeResponse(BaseModel):
    email: EmailStr
    verification_required: bool = True
    verification_preview_code: Optional[str] = None
    expires_in_minutes: int


class VerifyEmailRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=12)


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class PasswordResetRequest(BaseModel):
    email: EmailStr
    code: str = Field(..., min_length=4, max_length=12)
    new_password: str = Field(..., min_length=8)


class AccountDeletionCodeRequest(BaseModel):
    code: str = Field(..., min_length=4, max_length=12)


class CashDepositRequest(BaseModel):
    amount_usd: float = Field(..., gt=0, le=1000000)


class LoginTwoFactorConfirmRequest(BaseModel):
    username: str = Field(..., min_length=1)
    code: str = Field(..., min_length=4, max_length=12)


class LoginTwoFactorResendRequest(BaseModel):
    username: str = Field(..., min_length=1)


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


def _is_user_suspended(user) -> bool:
    suspended_until = getattr(user, "suspended_until", None)
    if suspended_until is None:
        return False
    if suspended_until.tzinfo is None:
        suspended_until = suspended_until.replace(tzinfo=timezone.utc)
    return suspended_until > datetime.now(timezone.utc)


def _suspension_error_response(user):
    suspended_until = getattr(user, "suspended_until", None)
    if suspended_until is not None and suspended_until.tzinfo is None:
        suspended_until = suspended_until.replace(tzinfo=timezone.utc)
    formatted_until = suspended_until.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC") if suspended_until else "an unknown time"
    reason = getattr(user, "suspension_reason", None)
    details = {"suspended_until": formatted_until}
    if reason:
        details["reason"] = reason
    return error_response(
        error_code=ErrorCode.FORBIDDEN,
        message=f"Your account is temporarily blocked until {formatted_until}",
        details=details,
        status_code=status.HTTP_403_FORBIDDEN,
    )


def _resolved_avatar_url(user) -> Optional[str]:
    stored_avatar = getattr(user, "avatar_url", None)
    if not stored_avatar:
        return None

    normalized = str(stored_avatar).strip()
    if not normalized:
        return None

    if normalized.startswith(("/api/auth/profile/avatar/",)):
        return normalized
    if normalized.startswith(("http://", "https://", "data:")):
        return None

    return f"/api/auth/profile/avatar/{user.id}"


def _user_response_from_model(user) -> UserResponse:
    cash_balance = float(getattr(user, "cash_balance_usd", 0) or 0)
    cash_reserved = float(getattr(user, "cash_reserved_usd", 0) or 0)
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
        cash_balance_usd=cash_balance,
        cash_reserved_usd=cash_reserved,
        cash_available_usd=max(cash_balance, 0.0),
        email_verified=getattr(user, "email_verified", False),
        login_two_factor_enabled=getattr(user, "login_two_factor_enabled", False),
        job_notifications_enabled=getattr(user, "job_notifications_enabled", False),
        created_at=user.created_at,
        updated_at=user.updated_at
    )


def _generate_one_time_code(length: int = 6) -> str:
    digits = "0123456789"
    return "".join(secrets.choice(digits) for _ in range(length))


def _allow_dev_code_preview() -> bool:
    return os.getenv("CASSIE_ALLOW_DEV_CODE_PREVIEW", "false").lower() in {"1", "true", "yes"}


def _code_matches(stored_code: Optional[str], submitted_code: str) -> bool:
    if not stored_code:
        return False
    return secrets.compare_digest(str(stored_code), submitted_code.strip())


def _issue_email_verification(user_id: int) -> tuple[str, int]:
    code = _generate_one_time_code()
    expires_in_minutes = CODE_EXPIRY_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    set_email_verification_code(user_id, code, expires_at)
    return code, expires_in_minutes


def _issue_password_reset(user_id: int) -> tuple[str, int]:
    code = _generate_one_time_code()
    expires_in_minutes = CODE_EXPIRY_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    set_password_reset_code(user_id, code, expires_at)
    return code, expires_in_minutes


def _issue_login_two_factor(user_id: int) -> tuple[str, int]:
    code = _generate_one_time_code()
    expires_in_minutes = CODE_EXPIRY_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    set_login_two_factor_code(user_id, code, expires_at)
    return code, expires_in_minutes


def _issue_account_deletion_code(user_id: int) -> tuple[str, int]:
    code = _generate_one_time_code()
    expires_in_minutes = CODE_EXPIRY_MINUTES
    expires_at = datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)
    set_account_deletion_code(user_id, code, expires_at)
    return code, expires_in_minutes


def _cooldown_remaining_seconds(expires_at: Optional[datetime], expiry_minutes: int) -> int:
    if expires_at is None:
        return 0

    normalized_expires_at = expires_at
    if normalized_expires_at.tzinfo is None:
        normalized_expires_at = normalized_expires_at.replace(tzinfo=timezone.utc)

    issued_at = normalized_expires_at - timedelta(minutes=expiry_minutes)
    elapsed_seconds = (datetime.now(timezone.utc) - issued_at).total_seconds()
    remaining_seconds = EMAIL_RESEND_COOLDOWN_SECONDS - int(elapsed_seconds)
    return max(0, remaining_seconds)


def _build_verification_email(username: str, code: str, expires_in_minutes: int) -> tuple[str, str, str]:
    subject = "Verify your CASSIE account"
    text_body = (
        f"Hello {username},\n\n"
        f"Your CASSIE verification code is: {code}\n"
        f"It expires in {expires_in_minutes} minutes.\n\n"
        "If you did not create this account, you can ignore this email."
    )
    html_body = (
        f"<p>Hello {username},</p>"
        f"<p>Your CASSIE verification code is:</p>"
        f"<p style=\"font-size:24px;font-weight:700;letter-spacing:4px;\">{code}</p>"
        f"<p>It expires in {expires_in_minutes} minutes.</p>"
        "<p>If you did not create this account, you can ignore this email.</p>"
    )
    return subject, text_body, html_body


def _build_password_reset_email(username: str, code: str, expires_in_minutes: int) -> tuple[str, str, str]:
    subject = "Reset your CASSIE password"
    text_body = (
        f"Hello {username},\n\n"
        f"Your CASSIE password reset code is: {code}\n"
        f"It expires in {expires_in_minutes} minutes.\n\n"
        "If you did not request a reset, you can ignore this email."
    )
    html_body = (
        f"<p>Hello {username},</p>"
        f"<p>Your CASSIE password reset code is:</p>"
        f"<p style=\"font-size:24px;font-weight:700;letter-spacing:4px;\">{code}</p>"
        f"<p>It expires in {expires_in_minutes} minutes.</p>"
        "<p>If you did not request a reset, you can ignore this email.</p>"
    )
    return subject, text_body, html_body


def _build_login_two_factor_challenge(user, *, code: str, expires_in_minutes: int) -> LoginTwoFactorChallengeResponse:
    email_sent = False
    if user.email:
        subject, text_body, html_body = build_login_two_factor_email(user.username, code, expires_in_minutes)
        email_sent = send_email(user.email, subject, text_body, html_body)

    return LoginTwoFactorChallengeResponse(
        username=user.username,
        email=user.email,
        two_factor_required=True,
        verification_preview_code=code if (not email_sent and _allow_dev_code_preview()) else None,
        expires_in_minutes=expires_in_minutes,
    )


def _build_account_deletion_email(username: str, code: str, expires_in_minutes: int) -> tuple[str, str, str]:
    subject = "Confirm CASSIE account deletion"
    text_body = (
        f"Hello {username},\n\n"
        f"Your CASSIE account deletion code is: {code}\n"
        f"It expires in {expires_in_minutes} minutes.\n\n"
        "If you did not request account deletion, ignore this email and your account will remain active."
    )
    html_body = (
        f"<p>Hello {username},</p>"
        "<p>Use this code to confirm permanent deletion of your CASSIE account:</p>"
        f"<p style=\"font-size:24px;font-weight:700;letter-spacing:4px;\">{code}</p>"
        f"<p>It expires in {expires_in_minutes} minutes.</p>"
        "<p>If you did not request account deletion, ignore this email and your account will remain active.</p>"
    )
    return subject, text_body, html_body


def _build_balance_receipt_email(username: str, amount_usd: float, total_balance_usd: float) -> tuple[str, str, str]:
    amount = f"${amount_usd:.2f}"
    total = f"${total_balance_usd:.2f}"
    subject = "CASSIE balance purchase confirmation"
    text_body = (
        f"Hello {username},\n\n"
        f"We added {amount} to your CASSIE job balance.\n"
        f"Your total balance is now {total}.\n\n"
        "Card details are not stored by CASSIE."
    )
    html_body = (
        f"<p>Hello {username},</p>"
        f"<p>We added <strong>{amount}</strong> to your CASSIE job balance.</p>"
        f"<p>Your total balance is now <strong>{total}</strong>.</p>"
        "<p>Card details are not stored by CASSIE.</p>"
    )
    return subject, text_body, html_body


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
    if _is_user_suspended(user):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=_suspension_error_response(user)["message"],
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
    purge_expired_unverified_users()

    is_valid, error_msg = validate_username(request.username)
    if not is_valid:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if not request.email:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Email is required for registration",
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
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

    normalized_invitation_code = normalize_invitation_code(request.invitation_code)
    if not normalized_invitation_code:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Invitation code is required for registration",
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Keep a unique per-user storage namespace in the legacy column.
    bucket_name = f"users/{request.username.lower()}"
    
    # Create user
    claimed_invitation = None
    user_created = False
    try:
        claimed_invitation = claim_invitation_code(normalized_invitation_code)
        user_data = UserCreate(
            username=request.username,
            email=request.email,
            password=request.password,
            bucket_name=bucket_name
        )
        user = create_user(user_data, email_verified=False)
        user_created = True
        attach_invitation_code_to_user(claimed_invitation.id, user.id)
        verification_code, expires_in_minutes = _issue_email_verification(user.id)
        email_sent = False
        if user.email:
            subject, text_body, html_body = _build_verification_email(user.username, verification_code, expires_in_minutes)
            email_sent = send_email(user.email, subject, text_body, html_body)
        if not email_sent and not _allow_dev_code_preview():
            return JSONResponse(
                content=error_response(
                    error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                    message="Account created, but the verification email could not be sent. Configure SMTP or enable CASSIE_ALLOW_DEV_CODE_PREVIEW for local development.",
                    status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                ),
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            )

        return success_response(
            data=VerificationChallengeResponse(
                email=request.email,
                verification_required=True,
                verification_preview_code=verification_code if (not email_sent and _allow_dev_code_preview()) else None,
                expires_in_minutes=expires_in_minutes,
            ).model_dump(exclude_none=True),
            message="Account created. Verify your email before logging in." if email_sent else "Account created. Verify your email before logging in. SMTP is not configured, so the code is shown in the app.",
            status_code=status.HTTP_201_CREATED
        )
        
    except ValueError as e:
        if claimed_invitation is not None and not user_created:
            release_invitation_code(claimed_invitation.id)
        response_status = status.HTTP_400_BAD_REQUEST if "invitation code" in str(e).lower() else status.HTTP_409_CONFLICT
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR if "invitation code" in str(e).lower() else ErrorCode.CONFLICT,
            message=str(e),
            status_code=response_status,
        )
        return JSONResponse(content=error_data, status_code=response_status)
    except Exception as e:
        if claimed_invitation is not None and not user_created:
            release_invitation_code(claimed_invitation.id)
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
    purge_expired_unverified_users()

    # Get user by username
    user = get_user_by_username(request.username)
    if user is None:
        error_data = unauthorized_response("Invalid username or password")
        return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)
    
    # Verify password
    if not verify_password(request.password, user.password_hash):
        error_data = unauthorized_response("Invalid username or password")
        return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)

    if _is_user_suspended(user):
        error_data = _suspension_error_response(user)
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    if user.email and not getattr(user, "email_verified", False):
        error_data = error_response(
            error_code=ErrorCode.FORBIDDEN,
            message="Please verify your email address before logging in",
            details={
                "verification_required": True,
                "email": user.email,
            },
            status_code=status.HTTP_403_FORBIDDEN,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    if getattr(user, "login_two_factor_enabled", False):
        if not user.email or not getattr(user, "email_verified", False):
            error_data = error_response(
                error_code=ErrorCode.FORBIDDEN,
                message="Two-factor login requires a verified email address. Please verify your email before signing in.",
                status_code=status.HTTP_403_FORBIDDEN,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

        login_code, expires_in_minutes = _issue_login_two_factor(user.id)
        challenge = _build_login_two_factor_challenge(user, code=login_code, expires_in_minutes=expires_in_minutes)
        return success_response(
            data=challenge.model_dump(exclude_none=True),
            message="Enter the login code sent to your email" if challenge.verification_preview_code is None else "Enter the login code shown below to finish signing in.",
        )
    
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


@router.post("/login/2fa/confirm")
async def confirm_login_two_factor(request: LoginTwoFactorConfirmRequest):
    purge_expired_unverified_users()

    user = get_user_by_username(request.username)
    if user is None:
        error_data = unauthorized_response("Invalid login code")
        return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)

    if _is_user_suspended(user):
        error_data = _suspension_error_response(user)
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    if not getattr(user, "login_two_factor_enabled", False):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Two-factor login is not enabled for this account",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if not user.email or not getattr(user, "email_verified", False):
        error_data = error_response(
            error_code=ErrorCode.FORBIDDEN,
            message="Two-factor login requires a verified email address.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    if not user.login_two_factor_code or not user.login_two_factor_expires_at:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="No login code is active. Start sign-in again to get a new code.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    expires_at = user.login_two_factor_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < datetime.now(timezone.utc):
        clear_login_two_factor_code(user.id)
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="The login code has expired. Start sign-in again or request a new code.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if not _code_matches(user.login_two_factor_code, request.code):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Incorrect login code",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    clear_login_two_factor_code(user.id)
    access_token = create_access_token(data={"user_id": user.id, "username": user.username})
    user_response = _user_response_from_model(get_user_by_id(user.id) or user)
    return success_response(
        data=LoginResponse(
            access_token=access_token,
            token_type="bearer",
            user=user_response,
        ).model_dump(),
        message="Login successful",
    )


@router.post("/login/2fa/resend")
async def resend_login_two_factor(request: LoginTwoFactorResendRequest):
    purge_expired_unverified_users()

    user = get_user_by_username(request.username)
    if user is None:
        return success_response(
            data={"username": request.username, "two_factor_required": True},
            message="If a login challenge is active, a new code will be sent.",
        )

    if not getattr(user, "login_two_factor_enabled", False):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Two-factor login is not enabled for this account",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if not user.email or not getattr(user, "email_verified", False):
        error_data = error_response(
            error_code=ErrorCode.FORBIDDEN,
            message="Two-factor login requires a verified email address.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    if not user.login_two_factor_code or not user.login_two_factor_expires_at:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Start sign-in again before requesting a new login code.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    cooldown_remaining = _cooldown_remaining_seconds(user.login_two_factor_expires_at, CODE_EXPIRY_MINUTES)
    if cooldown_remaining > 0:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"Please wait {cooldown_remaining} seconds before requesting another login code.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    login_code, expires_in_minutes = _issue_login_two_factor(user.id)
    challenge = _build_login_two_factor_challenge(user, code=login_code, expires_in_minutes=expires_in_minutes)
    return success_response(
        data=challenge.model_dump(exclude_none=True),
        message="A new login code has been sent" if challenge.verification_preview_code is None else "A new login code has been generated.",
    )


@router.post("/verify-email/request")
async def request_email_verification(request: ForgotPasswordRequest):
    purge_expired_unverified_users()

    user = get_user_by_email(request.email)
    if user is None:
        return success_response(
            data={"email": request.email, "verification_required": True},
            message=GENERIC_VERIFICATION_MESSAGE,
        )

    if user.email_verified:
        return success_response(
            data={
                "email": request.email,
                "verification_required": False,
                "expires_in_minutes": 0,
            },
            message="That email address is already verified",
        )

    cooldown_remaining = _cooldown_remaining_seconds(user.email_verification_expires_at, CODE_EXPIRY_MINUTES)
    if user.email_verification_code and cooldown_remaining > 0:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"Please wait {cooldown_remaining} seconds before requesting another verification email.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    verification_code, expires_in_minutes = _issue_email_verification(user.id)
    email_sent = False
    if user.email:
        subject, text_body, html_body = _build_verification_email(user.username, verification_code, expires_in_minutes)
        email_sent = send_email(user.email, subject, text_body, html_body)
    if not email_sent and not _allow_dev_code_preview():
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                message="Verification email could not be sent. Please try again later.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    return success_response(
        data=VerificationChallengeResponse(
            email=request.email,
            verification_required=True,
            verification_preview_code=verification_code if (not email_sent and _allow_dev_code_preview()) else None,
            expires_in_minutes=expires_in_minutes,
        ).model_dump(exclude_none=True),
        message="Verification code sent by email" if email_sent else "Verification code generated for local email confirmation",
    )


@router.post("/verify-email/confirm")
async def confirm_email_verification(request: VerifyEmailRequest):
    purge_expired_unverified_users()

    user = get_user_by_email(request.email)
    if user is None:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="The verification request is invalid or expired.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if user.email_verified:
        return success_response(
            data={"email": request.email, "verified": True},
            message="Email address is already verified",
        )

    if not user.email_verification_code or not user.email_verification_expires_at:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="No verification code is active for this account",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    now = datetime.now(timezone.utc)
    expires_at = user.email_verification_expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at < now:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="The verification code has expired. Request a new one and try again.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if not _code_matches(user.email_verification_code, request.code):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Incorrect verification code",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    updated_user = verify_user_email(user.id)
    return success_response(
        data={"email": request.email, "verified": True, "user": _user_response_from_model(updated_user).model_dump() if updated_user else None},
        message="Email verified successfully",
    )


@router.post("/forgot-password/request")
async def request_password_reset(request: ForgotPasswordRequest):
    purge_expired_unverified_users()

    user = get_user_by_email(request.email)
    if user is None:
        return success_response(
            data={"email": request.email},
            message=GENERIC_PASSWORD_RESET_MESSAGE,
        )

    cooldown_remaining = _cooldown_remaining_seconds(user.password_reset_expires_at, CODE_EXPIRY_MINUTES)
    if user.password_reset_code and cooldown_remaining > 0:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"Please wait {cooldown_remaining} seconds before requesting another password reset email.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    reset_code, expires_in_minutes = _issue_password_reset(user.id)
    email_sent = False
    if user.email:
        subject, text_body, html_body = _build_password_reset_email(user.username, reset_code, expires_in_minutes)
        email_sent = send_email(user.email, subject, text_body, html_body)
    if not email_sent and not _allow_dev_code_preview():
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
                message="Password reset email could not be sent. Please try again later.",
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            ),
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
    response_data = {
        "email": request.email,
        "expires_in_minutes": expires_in_minutes,
    }
    if not email_sent and _allow_dev_code_preview():
        response_data["reset_preview_code"] = reset_code

    return success_response(
        data=response_data,
        message="Password reset code sent by email" if email_sent else "Password reset code generated for local development",
    )


@router.post("/forgot-password/reset")
async def reset_password(request: PasswordResetRequest):
    purge_expired_unverified_users()

    user = get_user_by_email(request.email)
    if user is None:
        error_data = error_response(
            error_code=ErrorCode.NOT_FOUND,
            message="No account was found for that email address",
            status_code=status.HTTP_404_NOT_FOUND,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    is_valid, error_msg = validate_password(request.new_password)
    if not is_valid:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if not user.password_reset_code or not user.password_reset_expires_at:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="No password reset code is active for this account",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    now = datetime.now(timezone.utc)
    reset_expires_at = user.password_reset_expires_at
    if reset_expires_at.tzinfo is None:
        reset_expires_at = reset_expires_at.replace(tzinfo=timezone.utc)
    if reset_expires_at < now:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="The reset code has expired. Request a new one and try again.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if not _code_matches(user.password_reset_code, request.code):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Incorrect reset code",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    update_user_password(user.id, request.new_password)
    clear_password_reset_code(user.id)
    return success_response(
        data={"email": request.email, "password_reset": True},
        message="Password updated successfully",
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

    email_changed = payload.email is not None and payload.email != existing_user.email
    requested_two_factor = payload.login_two_factor_enabled
    requested_job_notifications = payload.job_notifications_enabled

    if email_changed and payload.email is not None:
        other_user = get_user_by_email(payload.email)
        if other_user is not None and other_user.id != current_user.id:
            error_data = error_response(
                error_code=ErrorCode.CONFLICT,
                message="That email address is already in use.",
                status_code=status.HTTP_409_CONFLICT,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_409_CONFLICT)

    if (requested_two_factor or requested_job_notifications) and (
        not existing_user.email or not getattr(existing_user, "email_verified", False)
    ):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="A verified email address is required before enabling login 2FA or job notifications.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    profile_payload = payload.model_copy(
        update={
            "email": None if email_changed else payload.email,
            "login_two_factor_enabled": None if email_changed else requested_two_factor,
            "job_notifications_enabled": None if email_changed else requested_job_notifications,
        }
    )

    updated_user = update_user_profile(current_user.id, profile_payload) or get_user_by_id(current_user.id)
    if email_changed and payload.email is not None:
        updated_user = reset_email_security_preferences(current_user.id, payload.email) or updated_user

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


@router.post("/profile/balance/deposit")
async def deposit_profile_balance(
    payload: CashDepositRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Add cash to the current user's CASSIE job balance."""
    if os.getenv("CASSIE_ENABLE_FAKE_PAYMENTS", "false").lower() not in {"1", "true", "yes"}:
        error_data = error_response(
            error_code=ErrorCode.FORBIDDEN,
            message="Self-service test balance deposits are disabled. Configure a real payment flow or explicitly enable CASSIE_ENABLE_FAKE_PAYMENTS in local development.",
            status_code=status.HTTP_403_FORBIDDEN,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_403_FORBIDDEN)

    try:
        deposit_user_cash(current_user.id, payload.amount_usd)
        updated_user = get_user_by_id(current_user.id)
        if updated_user is None:
            error_data = unauthorized_response("User not found")
            return JSONResponse(content=error_data, status_code=status.HTTP_401_UNAUTHORIZED)

        email_sent = False
        if updated_user.email:
            subject, text_body, html_body = _build_balance_receipt_email(
                updated_user.username,
                payload.amount_usd,
                float(getattr(updated_user, "cash_balance_usd", 0) or 0),
            )
            email_sent = send_email(updated_user.email, subject, text_body, html_body)
            if not email_sent:
                logger.warning("Balance confirmation email could not be sent to user %s", updated_user.id)

        return success_response(
            data=_user_response_from_model(updated_user).model_dump(),
            message="Balance updated successfully" if email_sent else "Balance updated successfully; confirmation email could not be sent",
        )
    except ValueError as exc:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(exc),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/profile/delete/request")
async def request_account_deletion(current_user: UserResponse = Depends(get_current_user)):
    """Send a deletion confirmation code to the verified account email."""
    if not current_user.email or not getattr(current_user, "email_verified", False):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="A verified email address is required before deleting an account.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    existing_code, existing_expires_at = get_account_deletion_code_state(current_user.id)
    cooldown_remaining = _cooldown_remaining_seconds(existing_expires_at, CODE_EXPIRY_MINUTES)
    if existing_code and cooldown_remaining > 0:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=f"Please wait {cooldown_remaining} seconds before requesting another account deletion email.",
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    deletion_code, expires_in_minutes = _issue_account_deletion_code(current_user.id)
    subject, text_body, html_body = _build_account_deletion_email(current_user.username, deletion_code, expires_in_minutes)
    email_sent = send_email(current_user.email, subject, text_body, html_body)

    if not email_sent:
        error_data = error_response(
            error_code=ErrorCode.EXTERNAL_SERVICE_ERROR,
            message="Failed to send the account deletion email. Please try again.",
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_503_SERVICE_UNAVAILABLE)

    return success_response(
        data={"email": current_user.email, "expires_in_minutes": expires_in_minutes},
        message="Account deletion confirmation code sent by email",
    )


@router.post("/profile/delete/confirm")
async def confirm_account_deletion(
    request: AccountDeletionCodeRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    """Delete the authenticated user after email-code confirmation."""
    stored_code, expires_at = get_account_deletion_code_state(current_user.id)
    if not stored_code or not expires_at:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="No account deletion confirmation code is active. Request a new one and try again.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    normalized_expires_at = expires_at.replace(tzinfo=timezone.utc) if expires_at.tzinfo is None else expires_at
    if normalized_expires_at < datetime.now(timezone.utc):
        clear_account_deletion_code(current_user.id)
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="The account deletion code has expired. Request a new one and try again.",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if not _code_matches(stored_code, request.code):
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Incorrect account deletion code",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    clear_account_deletion_code(current_user.id)
    deleted = delete_user_account(current_user.id)
    if not deleted:
        error_data = error_response(
            error_code=ErrorCode.NOT_FOUND,
            message="User account not found",
            status_code=status.HTTP_404_NOT_FOUND,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

    return success_response(
        data={"deleted": True},
        message="Account deleted successfully",
    )


@router.delete("/profile")
async def delete_profile(current_user: UserResponse = Depends(get_current_user)):
    """Legacy direct-delete route; deletion now requires an emailed verification step."""
    error_data = error_response(
        error_code=ErrorCode.VALIDATION_ERROR,
        message="Account deletion now requires email confirmation. Request a deletion code first.",
        status_code=status.HTTP_400_BAD_REQUEST,
    )
    return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)


@router.post("/profile/avatar")
async def upload_profile_avatar(
    file: UploadFile = File(...),
    current_user: UserResponse = Depends(get_current_user),
):
    """Upload a profile avatar image and update the current user profile."""
    content_type = (file.content_type or "").lower()
    allowed_types = {"image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp"}
    if content_type not in allowed_types:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Profile pictures must be PNG, JPEG, GIF, or WEBP",
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    suffix = os.path.splitext(file.filename or "")[1].lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".gif", ".webp"}:
        suffix = {
            "image/png": ".png",
            "image/jpeg": ".jpg",
            "image/jpg": ".jpg",
            "image/gif": ".gif",
            "image/webp": ".webp",
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
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Avatar not found")

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
