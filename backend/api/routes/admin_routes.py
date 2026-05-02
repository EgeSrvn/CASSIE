"""
Admin-only API routes for CASSIE.

All endpoints require a valid bearer token with role=admin (is_admin=True).
Backend enforces this server-side — frontend role flags are not trusted.

Demo code management endpoints are only active when DEMO_MODE_ENABLED=true.
User management endpoints are always active for admins.
"""

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api.models.user_model import UserResponse
from backend.api.routes.auth import get_current_admin
from backend.api.services.demo_service import (
    deactivate_demo_code,
    generate_demo_codes,
    get_demo_codes,
)
from backend.api.services.user_service import (
    get_all_users,
    set_user_active,
    set_user_admin,
)
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger
from backend.api.utils.response_builder import error_response, success_response, ErrorCode

logger = get_logger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])


# ============================================================================
# Demo Code Management (only when DEMO_MODE_ENABLED=true)
# ============================================================================


class GenerateDemoCodesRequest(BaseModel):
    count: int = Field(1, ge=1, le=100, description="Number of demo codes to generate")
    expires_at: Optional[datetime] = Field(None, description="Expiry datetime (UTC); null = no expiry")


@router.post("/demo-codes/generate")
async def generate_codes(
    request: GenerateDemoCodesRequest,
    current_admin: UserResponse = Depends(get_current_admin),
):
    """
    Generate one-time demo codes.

    Returns plaintext codes ONCE — they are never stored and cannot be retrieved again.
    Only available when DEMO_MODE_ENABLED=true.
    """
    config = get_config()
    if not config.demo.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo mode is not enabled")

    try:
        plaintext_codes = generate_demo_codes(
            admin_user_id=current_admin.id,
            count=request.count,
            expires_at=request.expires_at,
        )
    except Exception:
        logger.error("Error generating demo codes", exc_info=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to generate demo codes",
        )

    logger.info(
        "Admin generated demo codes",
        extra={"admin_id": current_admin.id, "count": len(plaintext_codes)},
    )
    return success_response(
        data={
            "codes": plaintext_codes,
            "note": "These codes are shown only once. Store them securely before sharing.",
        },
        message=f"Generated {len(plaintext_codes)} demo code(s).",
    )


@router.get("/demo-codes")
async def list_codes(
    current_admin: UserResponse = Depends(get_current_admin),
):
    """
    List all demo codes with metadata.

    Never returns code hashes or plaintext codes — only masked prefixes and status.
    Only available when DEMO_MODE_ENABLED=true.
    """
    config = get_config()
    if not config.demo.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo mode is not enabled")

    codes = get_demo_codes()
    return success_response(data={"codes": codes}, message="Demo codes listed.")


@router.post("/demo-codes/{code_id}/deactivate")
async def deactivate_code(
    code_id: int,
    current_admin: UserResponse = Depends(get_current_admin),
):
    """
    Deactivate an unused demo code so it can no longer be activated.

    Already-used codes cannot be reactivated.
    Only available when DEMO_MODE_ENABLED=true.
    """
    config = get_config()
    if not config.demo.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Demo mode is not enabled")

    success = deactivate_demo_code(code_id)
    if not success:
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.NOT_FOUND,
                message="Code not found, already used, or already deactivated.",
                status_code=status.HTTP_404_NOT_FOUND,
            ),
            status_code=status.HTTP_404_NOT_FOUND,
        )

    logger.info("Demo code deactivated by admin", extra={"admin_id": current_admin.id, "code_id": code_id})
    return success_response(data={"code_id": code_id}, message="Demo code deactivated.")


# ============================================================================
# User / Account Management
# ============================================================================


@router.get("/users")
async def list_users(
    current_admin: UserResponse = Depends(get_current_admin),
):
    """List all user accounts. Admin only."""
    users = get_all_users()
    user_data = [
        {
            "id": u.id,
            "username": u.username,
            "email": u.email,
            "is_admin": getattr(u, "is_admin", False),
            "is_active": getattr(u, "is_active", True),
            "email_verified": getattr(u, "email_verified", False),
            "created_at": u.created_at.isoformat() if u.created_at else None,
            "updated_at": u.updated_at.isoformat() if u.updated_at else None,
        }
        for u in users
    ]
    return success_response(data={"users": user_data}, message="Users listed.")


@router.post("/users/{user_id}/make-admin")
async def make_admin(
    user_id: int,
    current_admin: UserResponse = Depends(get_current_admin),
):
    """Grant admin status to a user account. Admin only."""
    updated = set_user_admin(user_id, True)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info("Admin granted", extra={"admin_id": current_admin.id, "target_user_id": user_id})
    return success_response(data={"user_id": user_id, "is_admin": True}, message="Admin status granted.")


@router.post("/users/{user_id}/remove-admin")
async def remove_admin(
    user_id: int,
    current_admin: UserResponse = Depends(get_current_admin),
):
    """Revoke admin status from a user account. Cannot remove own admin status."""
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot remove your own admin status.",
        )

    updated = set_user_admin(user_id, False)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info("Admin revoked", extra={"admin_id": current_admin.id, "target_user_id": user_id})
    return success_response(data={"user_id": user_id, "is_admin": False}, message="Admin status revoked.")


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    user_id: int,
    current_admin: UserResponse = Depends(get_current_admin),
):
    """Deactivate a user account. Admin only."""
    if user_id == current_admin.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Cannot deactivate your own account.",
        )

    updated = set_user_active(user_id, False)
    if not updated:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    logger.info("User deactivated by admin", extra={"admin_id": current_admin.id, "target_user_id": user_id})
    return success_response(data={"user_id": user_id, "is_active": False}, message="User account deactivated.")
