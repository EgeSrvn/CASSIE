"""
Demo mode public endpoints for CASSIE.

These endpoints are only active when DEMO_MODE_ENABLED=true.
They allow public/demo users to validate demo codes and list available mock datasets.
"""

import json
import os
from pathlib import Path

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from backend.api.routes.auth import get_current_user_or_demo
from backend.api.services.auth_service import create_demo_token
from backend.api.services.demo_service import validate_and_consume_demo_code
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger
from backend.api.utils.response_builder import error_response, success_response, ErrorCode
from fastapi import Depends
from backend.api.models.user_model import UserResponse

logger = get_logger(__name__)

router = APIRouter(prefix="/demo", tags=["demo"])


class ValidateCodeRequest(BaseModel):
    code: str = Field(..., min_length=1, max_length=64)


@router.post("/validate-code")
async def validate_demo_code(request: ValidateCodeRequest):
    """
    Validate a one-time demo code and issue a demo session token.

    Only available when DEMO_MODE_ENABLED=true.
    On success: returns a JWT demo session token (stored client-side like a normal bearer token).
    On failure: returns a generic error — never reveals the specific reason for rejection.
    """
    config = get_config()
    if not config.demo.enabled:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    normalized = request.code.strip().upper()
    if len(normalized) != config.demo.code_length:
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Invalid or expired demo code.",
                status_code=status.HTTP_400_BAD_REQUEST,
            ),
            status_code=status.HTTP_400_BAD_REQUEST,
        )

    try:
        session_info = validate_and_consume_demo_code(normalized)
    except ValueError:
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.UNAUTHORIZED,
                message="Invalid or expired demo code.",
                status_code=status.HTTP_401_UNAUTHORIZED,
            ),
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
    except Exception:
        logger.error("Unexpected error during demo code validation", exc_info=True)
        return JSONResponse(
            content=error_response(
                error_code=ErrorCode.INTERNAL_ERROR,
                message="Invalid or expired demo code.",
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            ),
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    token = create_demo_token(
        session_id=session_info["session_id"],
        demo_code_id=session_info["demo_code_id"],
    )
    return success_response(
        data={
            "access_token": token,
            "token_type": "bearer",
            "role": "demo",
        },
        message="Demo session started.",
    )


@router.get("/datasets")
async def list_demo_datasets(
    current_user: UserResponse = Depends(get_current_user_or_demo),
):
    """
    List available predefined mock/synthetic datasets for demo pipelines.

    Accessible by demo users and admin users.
    Returns only safe metadata — no raw filesystem paths.
    """
    config = get_config()
    if not config.demo.enabled and getattr(current_user, "id", None) == 0:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

    manifest_path = Path(config.demo.data_root) / "manifest.json"

    if not manifest_path.exists():
        return success_response(data={"datasets": []}, message="No demo datasets configured.")

    try:
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        logger.warning("Failed to read demo dataset manifest", exc_info=True)
        return success_response(data={"datasets": []}, message="Demo datasets unavailable.")

    datasets = manifest.get("datasets", [])
    # Strip internal file paths — only expose safe metadata to the frontend
    safe_datasets = [
        {
            "dataset_id": d.get("dataset_id"),
            "display_name": d.get("display_name"),
            "description": d.get("description"),
            "organism": d.get("organism"),
            "type": d.get("type"),
            "size_mb": d.get("size_mb"),
            "allowed_pipeline_types": d.get("allowed_pipeline_types", []),
        }
        for d in datasets
        if d.get("dataset_id")
    ]

    return success_response(data={"datasets": safe_datasets}, message="Demo datasets listed.")
