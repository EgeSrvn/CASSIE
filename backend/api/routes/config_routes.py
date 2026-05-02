"""
Public configuration endpoint for CASSIE frontend.

Exposes only safe, non-secret configuration values needed by the frontend.
No authentication required.
"""

from fastapi import APIRouter

from backend.api.utils.config_loader import get_config
from backend.api.utils.response_builder import success_response

router = APIRouter(prefix="/config", tags=["config"])


@router.get("/public")
async def get_public_config():
    """
    Return safe public configuration values for the frontend.

    Only demo_mode_enabled and demo_code_length are exposed.
    No secrets, credentials, internal paths, or bootstrap config are included.
    """
    config = get_config()
    return success_response(
        data={
            "demo_mode_enabled": config.demo.enabled,
            "demo_code_length": config.demo.code_length,
        },
        message="Public configuration",
    )
