"""
Tools API routes for CASSIE backend.

This module provides:
- Get available tools list
- Get input requirements
- Get intent-driven pipeline recommendations
"""

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from pydantic import BaseModel, Field

from backend.api.utils.response_builder import (
    success_response,
    error_response,
    ErrorCode
)
from backend.api.utils.logger import get_logger
from backend.api.services.intent_recommender import (
    get_recommendation_intents,
    recommend_pipelines,
)
from tool_registry import (
    get_tool_by_index,
    get_tool_by_id,
    get_tool_registry,
    get_tool_requirements as get_registry_tool_requirements,
    tool_produces_requirement,
)

logger = get_logger(__name__)

router = APIRouter(prefix="/tools", tags=["tools"])


class RecommendationFileSummary(BaseModel):
    filename: str
    file_format: Optional[str] = None


class RecommendationRequest(BaseModel):
    intent_ids: List[str] = Field(default_factory=list)
    files: List[RecommendationFileSummary] = Field(default_factory=list)


@router.get("")
async def get_available_tools():
    """
    Get list of available bioinformatics tools.
    
    Returns:
        List of available tools with their metadata
    """
    try:
        available_tools = get_tool_registry()
        tools_list = []
        for idx, tool in enumerate(available_tools):
            tools_list.append({
                "id": idx,
                "tool_id": tool["id"],
                "name": tool["name"],
                "description": tool.get("description", ""),
                "type": tool.get("type", "unknown"),
                "enabled": True,  # All tools from emulation are enabled
                "editable_flags": tool.get("editable_flags", []),
                "default_flag_values": tool.get("default_flag_values", {}),
            })
        
        return success_response(
            data=tools_list,
            message="Available tools retrieved successfully"
        )
        
    except Exception as e:
        logger.error(f"Error getting available tools: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve available tools",
            status_code=500
        )
        return JSONResponse(content=error_data, status_code=500)


@router.get("/recommendation-intents")
async def list_recommendation_intents():
    try:
        return success_response(
            data=get_recommendation_intents(),
            message="Recommendation intents retrieved successfully",
        )
    except Exception as e:
        logger.error(f"Error getting recommendation intents: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve recommendation intents",
            status_code=500,
        )
        return JSONResponse(content=error_data, status_code=500)


@router.post("/recommendations")
async def get_recommendations(request: RecommendationRequest):
    try:
        recommendation_data = recommend_pipelines(
            intent_ids=request.intent_ids,
            file_entries=[file.model_dump() for file in request.files],
        )
        return success_response(
            data=recommendation_data,
            message="Pipeline recommendations generated successfully",
        )
    except Exception as e:
        logger.error(f"Error generating recommendations: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to generate pipeline recommendations",
            status_code=500,
        )
        return JSONResponse(content=error_data, status_code=500)


@router.get("/requirements")
async def get_tool_requirements(
    tool_indices: Optional[str] = Query(None, description="Comma-separated tool indices (e.g., '0,1,2')")
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
        
        selected_tools = [
            tool
            for idx in indices
            for tool in [get_tool_by_index(idx)]
            if tool
        ]
        selected_tool_ids = {tool["id"] for tool in selected_tools}

        # Get tools and their requirements
        tool_requirements = []
        for idx in indices:
            tool = get_tool_by_index(idx)
            if not tool:
                continue

            tool_id = tool["id"]
            tool_name = tool["name"]
            
            # Get input requirements for this tool
            requirements = get_registry_tool_requirements(tool_id)
            if requirements:
                # Check if inputs are intermediate (from previous tools)
                processed_requirements = []
                for req in requirements:
                    req_copy = req.copy()
                    producer_name = None
                    for candidate_tool in selected_tools:
                        candidate_tool_id = candidate_tool["id"]
                        if candidate_tool_id == tool_id:
                            continue
                        if tool_produces_requirement(candidate_tool, str(req.get("type") or "")):
                            producer_name = candidate_tool.get("name") or get_tool_by_id(candidate_tool_id).get("name", candidate_tool_id)
                            break
                    req_copy["is_intermediate"] = producer_name is not None
                    if producer_name:
                        req_copy["source_tool"] = producer_name
                    
                    processed_requirements.append(req_copy)
                
                tool_requirements.append({
                    "tool_index": idx,
                    "tool_id": tool_id,
                    "tool_name": tool_name,
                    "tool_type": tool.get("type", "unknown"),
                    "description": tool.get("description", ""),
                    "requirements": processed_requirements
                })
        
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
