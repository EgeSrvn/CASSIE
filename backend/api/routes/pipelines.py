"""
Pipeline routes for managing user-created visual pipelines.

This module provides REST API endpoints for CRUD operations on pipelines.
Pipelines are visual representations (nodes/edges) created using ReactFlow.
"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import JSONResponse

from backend.api.models.pipeline_model import (
    PipelineCreate,
    PipelineUpdate,
    PipelineResponse
)
from backend.api.models.engagement_model import ReportCreate, VoteRequest
from backend.api.models.user_model import UserResponse
from backend.api.routes.auth import get_current_user, get_current_user_optional
from backend.api.services.engagement_service import create_report, set_vote
from backend.api.services.pipeline_service import (
    create_pipeline,
    get_pipeline_by_id,
    get_pipeline_by_id_public,
    get_pipelines_by_user,
    get_shared_pipelines,
    update_pipeline,
    delete_pipeline,
    share_pipeline,
    unshare_pipeline
)
from backend.api.services.pipeline_analyzer import analyze_pipeline_requirements
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    not_found_response,
    ErrorCode
)
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/pipelines", tags=["pipelines"])


@router.get("", response_model=dict)
async def list_pipelines(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List all pipelines for the current user.
    
    Returns:
        JSONResponse: List of pipelines
    """
    try:
        pipelines = get_pipelines_by_user(current_user.id)
        pipeline_responses = [PipelineResponse.model_validate(p) for p in pipelines]
        
        return success_response(
            data=pipeline_responses,
            message=f"Found {len(pipeline_responses)} pipeline(s)"
        )
    except Exception as e:
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to list pipelines: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("", response_model=dict, status_code=status.HTTP_201_CREATED)
async def create_pipeline_endpoint(
    pipeline_data: PipelineCreate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create a new pipeline.
    
    Args:
        pipeline_data: Pipeline creation data (name, description, nodes, edges)
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Created pipeline
    """
    try:
        pipeline = create_pipeline(current_user.id, pipeline_data)
        pipeline_response = PipelineResponse.model_validate(pipeline)
        
        return success_response(
            data=pipeline_response,
            message="Pipeline created successfully",
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
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to create pipeline: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/shared", response_model=dict)
async def list_shared_pipelines(
    q: Optional[str] = Query(None, description="Partial search text for pipeline names or contained tool labels"),
    sort: str = Query("recent", description="Sort shared pipelines by recent or popular"),
    current_user: Optional[UserResponse] = Depends(get_current_user_optional),
):
    """
    List all shared pipelines (public access, no authentication required).
    
    Returns:
        JSONResponse: List of shared pipelines
    """
    try:
        pipelines = get_shared_pipelines(
            search_query=q,
            requester_user_id=current_user.id if current_user else None,
            sort_by=sort,
        )
        pipeline_responses = [PipelineResponse.model_validate(p) for p in pipelines]
        
        return success_response(
            data=pipeline_responses,
            message=f"Found {len(pipeline_responses)} shared pipeline(s)"
        )
    except Exception as e:
        logger.error(f"Error listing shared pipelines: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to list shared pipelines: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{pipeline_id}", response_model=dict)
async def get_pipeline(
    pipeline_id: int,
    current_user: Optional[UserResponse] = Depends(get_current_user_optional)
):
    """
    Get a pipeline by ID (must belong to user or be shared).
    Allows viewing shared pipelines without authentication.
    
    Args:
        pipeline_id: ID of the pipeline
        current_user: Current authenticated user (optional)
        
    Returns:
        JSONResponse: Pipeline details
    """
    user_id = current_user.id if current_user else None
    # Try to get pipeline - if user is authenticated, check ownership or shared
    # If not authenticated, only allow shared pipelines
    if user_id:
        pipeline = get_pipeline_by_id(pipeline_id, user_id)
    else:
        pipeline = get_pipeline_by_id_public(pipeline_id)
    
    if not pipeline:
        error_data = not_found_response("Pipeline", pipeline_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    pipeline_response = PipelineResponse.model_validate(pipeline)
    return success_response(
        data=pipeline_response,
        message="Pipeline retrieved successfully"
    )


@router.put("/{pipeline_id}", response_model=dict)
async def update_pipeline_endpoint(
    pipeline_id: int,
    pipeline_data: PipelineUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Update a pipeline.
    
    Args:
        pipeline_id: ID of the pipeline to update
        pipeline_data: Update data (only provided fields will be updated)
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Updated pipeline
    """
    try:
        pipeline = update_pipeline(pipeline_id, current_user.id, pipeline_data)
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if not pipeline:
        error_data = not_found_response("Pipeline", pipeline_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    pipeline_response = PipelineResponse.model_validate(pipeline)
    return success_response(
        data=pipeline_response,
        message="Pipeline updated successfully"
    )


@router.get("/{pipeline_id}/requirements", response_model=dict)
async def get_pipeline_requirements(
    pipeline_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Get input requirements for a pipeline.
    
    Analyzes the pipeline graph to determine what input files are needed.
    
    Args:
        pipeline_id: ID of the pipeline
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Pipeline requirements (input_requirements, tools, etc.)
    """
    try:
        pipeline = get_pipeline_by_id(pipeline_id, current_user.id)
        
        if not pipeline:
            error_data = not_found_response("Pipeline", pipeline_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        requirements = analyze_pipeline_requirements(pipeline)
        
        return success_response(
            data=requirements,
            message="Pipeline requirements retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error getting pipeline requirements: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to get pipeline requirements: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.delete("/{pipeline_id}", response_model=dict)
async def delete_pipeline_endpoint(
    pipeline_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Delete a pipeline.
    
    Args:
        pipeline_id: ID of the pipeline to delete
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Success message
    """
    deleted = delete_pipeline(pipeline_id, current_user.id)
    
    if not deleted:
        error_data = not_found_response("Pipeline", pipeline_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    return success_response(
        data=None,
        message="Pipeline deleted successfully"
    )


@router.post("/{pipeline_id}/share", response_model=dict)
async def share_pipeline_endpoint(
    pipeline_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Share a pipeline with the community.
    
    Args:
        pipeline_id: ID of the pipeline to share
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Updated pipeline
    """
    pipeline = share_pipeline(pipeline_id, current_user.id)
    
    if not pipeline:
        error_data = not_found_response("Pipeline", pipeline_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    pipeline_response = PipelineResponse.model_validate(pipeline)
    return success_response(
        data=pipeline_response,
        message="Pipeline shared successfully"
    )


@router.post("/{pipeline_id}/unshare", response_model=dict)
async def unshare_pipeline_endpoint(
    pipeline_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Unshare a pipeline (make it private).
    
    Args:
        pipeline_id: ID of the pipeline to unshare
        current_user: Current authenticated user
        
    Returns:
        JSONResponse: Updated pipeline
    """
    pipeline = unshare_pipeline(pipeline_id, current_user.id)
    
    if not pipeline:
        error_data = not_found_response("Pipeline", pipeline_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    pipeline_response = PipelineResponse.model_validate(pipeline)
    return success_response(
        data=pipeline_response,
        message="Pipeline unshared successfully"
    )


@router.post("/{pipeline_id}/vote", response_model=dict)
async def vote_pipeline_endpoint(
    pipeline_id: int,
    payload: VoteRequest,
    current_user: UserResponse = Depends(get_current_user),
):
    try:
        summary = set_vote(
            target_type="pipeline",
            target_id=pipeline_id,
            user_id=current_user.id,
            vote_type=payload.vote_type,
        )
        return success_response(data=summary, message="Pipeline vote updated successfully")
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error voting on pipeline {pipeline_id}: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to update pipeline vote",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/{pipeline_id}/report", response_model=dict)
async def report_pipeline_endpoint(
    pipeline_id: int,
    payload: ReportCreate,
    current_user: UserResponse = Depends(get_current_user),
):
    try:
        report = create_report(
            target_type="pipeline",
            target_id=pipeline_id,
            reporter_user_id=current_user.id,
            payload=payload,
        )
        return success_response(data=report, message="Pipeline reported successfully")
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error reporting pipeline {pipeline_id}: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to report pipeline",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
