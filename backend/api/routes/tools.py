"""
Tools API routes for CASSIE backend.

This module provides:
- Get available tools list
"""

from fastapi import APIRouter, Depends, Query
from fastapi.responses import JSONResponse
from typing import List, Dict, Any, Optional
import sys
from pathlib import Path

from backend.api.routes.auth import get_current_user
from backend.api.models.user_model import UserResponse
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    ErrorCode
)
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


@router.get("")
async def get_available_tools(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get list of available bioinformatics tools.
    
    Returns:
        List of available tools with their metadata
    """
    try:
        # Add project root to path so we can import emulation as a package
        project_root = Path(__file__).parent.parent.parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from emulation.nextflow_manager import AVAILABLE_TOOLS
        
        # Format tools for frontend
        tools_list = []
        for idx, tool in enumerate(AVAILABLE_TOOLS):
            tools_list.append({
                "id": idx,
                "name": tool["name"],
                "description": tool.get("description", ""),
                "type": tool.get("type", "unknown"),
                "enabled": True  # All tools from emulation are enabled
            })
        
        return success_response(
            data=tools_list,
            message="Available tools retrieved successfully"
        )
        
    except ImportError as e:
        logger.error(f"Could not import AVAILABLE_TOOLS from emulation: {e}", exc_info=True)
        # Fallback to basic tool list
        fallback_tools = [
            {
                "id": 0,
                "name": "FastQC",
                "description": "Quality control for raw sequence data",
                "type": "qc",
                "enabled": True
            }
        ]
        return success_response(
            data=fallback_tools,
            message="Available tools retrieved (fallback mode)"
        )
    except Exception as e:
        logger.error(f"Error getting available tools: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve available tools",
            status_code=500
        )
        return JSONResponse(content=error_data, status_code=500)


@router.get("/requirements")
async def get_tool_requirements(
    tool_indices: Optional[str] = Query(None, description="Comma-separated tool indices (e.g., '0,1,2')"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get input requirements for specified tools.
    
    Args:
        tool_indices: Comma-separated list of tool indices (e.g., "0,1,2")
        current_user: Current authenticated user
        
    Returns:
        List of tool requirements with information about which inputs are intermediate
    """
    try:
        from backend.api.services.pipeline_analyzer import TOOL_INPUT_REQUIREMENTS
        from emulation.nextflow_manager import AVAILABLE_TOOLS
        
        if not tool_indices:
            return success_response(
                data=[],
                message="No tool indices provided"
            )
        
        # Parse tool indices
        try:
            indices = [int(idx.strip()) for idx in tool_indices.split(',')]
        except ValueError:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Invalid tool indices format. Use comma-separated numbers (e.g., '0,1,2')",
                status_code=400
            )
            return JSONResponse(content=error_data, status_code=400)
        
        # Get tools and their requirements
        tool_requirements = []
        tools_seen = set()
        has_spades = False
        
        for idx in indices:
            if idx < 0 or idx >= len(AVAILABLE_TOOLS):
                continue
            
            tool = AVAILABLE_TOOLS[idx]
            tool_id = tool["id"]
            tool_name = tool["name"]
            
            # Get input requirements for this tool
            if tool_id in TOOL_INPUT_REQUIREMENTS:
                requirements = TOOL_INPUT_REQUIREMENTS[tool_id]
                
                # Check if inputs are intermediate (from previous tools)
                processed_requirements = []
                for req in requirements:
                    req_copy = req.copy()
                    
                    # QUAST assembly comes from SPAdes if SPAdes is before it
                    if tool_id == "QUAST" and req["type"] == "assembly" and has_spades:
                        req_copy["is_intermediate"] = True
                        req_copy["source_tool"] = "SPAdes"
                    else:
                        req_copy["is_intermediate"] = False
                    
                    processed_requirements.append(req_copy)
                
                tool_requirements.append({
                    "tool_index": idx,
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "tool_type": tool.get("type", "unknown"),
                    "requirements": processed_requirements
                })
                
                if tool_id == "SPADES":
                    has_spades = True
        
        return success_response(
            data=tool_requirements,
            message="Tool requirements retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error getting tool requirements: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve tool requirements",
            status_code=500
        )
        return JSONResponse(content=error_data, status_code=500)

