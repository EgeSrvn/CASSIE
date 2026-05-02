"""
Runtime and cost estimation routes for CASSIE backend.
"""

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool
from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any

from backend.api.routes.auth import get_current_user, get_current_user_optional
from backend.api.models.user_model import UserResponse
from backend.api.services.pipeline_service import get_pipeline_by_id, get_pipeline_by_id_public
from backend.api.services.runtime_estimator_service import (
    RuntimeInputAssignment,
    estimate_runtime_for_pipeline_graph,
    estimate_runtime_for_tool_indices,
)
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    ErrorCode
)
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

router = APIRouter(prefix="/estimator", tags=["cost-estimation"])


# Request/Response models
class CostEstimateRequest(BaseModel):
    """Request model for cost estimation."""
    workflow_id: int = Field(..., description="Workflow ID")
    data_size_gb: Optional[float] = Field(None, description="Estimated data size in GB")
    assembler: Optional[str] = Field(None, description="Assembler tool to use")
    cloud_provider: Optional[str] = Field(None, description="Cloud provider (aws, gcp, azure)")
    estimated_runtime_hours: Optional[float] = Field(None, description="Estimated runtime in hours")


class CostEstimateResponse(BaseModel):
    """Response model for cost estimation."""
    estimated_cost_usd: float = Field(..., description="Estimated cost in USD")
    estimated_runtime_hours: float = Field(..., description="Estimated runtime in hours")
    resource_requirements: Dict[str, Any] = Field(..., description="Resource requirements")
    breakdown: Dict[str, Any] = Field(..., description="Cost breakdown by component")


class RuntimeEstimateRequest(BaseModel):
    class InputAssignment(BaseModel):
        tool_id: str
        requirement_type: str
        total_input_size_mib: float
        compressed_input_size_mib: Optional[float] = 0.0
        file_formats: Optional[List[str]] = None

    tool_indices: Optional[List[int]] = None
    pipeline_id: Optional[int] = None
    vm_name: Optional[str] = None
    input_assignments: Optional[List[InputAssignment]] = None


@router.post("/estimate")
async def estimate_job_cost(
    request: CostEstimateRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Estimate the cost of running a job (placeholder implementation).
    
    Args:
        request: Cost estimation request
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with cost estimation
    """
    try:
        # Placeholder implementation - returns mock estimates
        # TODO: Implement actual cost estimation logic
        
        # Mock cost calculation
        base_cost = 5.0  # Base cost in USD
        data_cost = (request.data_size_gb or 10.0) * 0.1  # $0.10 per GB
        runtime_cost = (request.estimated_runtime_hours or 2.0) * 2.5  # $2.50 per hour
        
        estimated_cost = base_cost + data_cost + runtime_cost
        
        # Mock resource requirements
        resource_requirements = {
            "cpu_cores": 4,
            "memory_gb": 16,
            "storage_gb": request.data_size_gb or 10.0,
            "network_bandwidth_mbps": 100
        }
        
        # Mock cost breakdown
        breakdown = {
            "base_cost": base_cost,
            "data_storage": data_cost,
            "compute_time": runtime_cost,
            "network_transfer": 0.5,
            "total": estimated_cost
        }
        
        estimate_response = CostEstimateResponse(
            estimated_cost_usd=round(estimated_cost, 2),
            estimated_runtime_hours=request.estimated_runtime_hours or 2.0,
            resource_requirements=resource_requirements,
            breakdown=breakdown
        )
        
        return JSONResponse(
            content=success_response(
                data=estimate_response.model_dump(),
                message="Cost estimation completed (placeholder)",
                status_code=status.HTTP_200_OK
            ),
            status_code=status.HTTP_200_OK
        )
        
    except Exception as e:
        logger.error(f"Error estimating job cost: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to estimate job cost",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/runtime")
async def estimate_runtime(
    request: RuntimeEstimateRequest,
    current_user: Optional[UserResponse] = Depends(get_current_user_optional),
):
    """Estimate job runtime from selected tools or a saved pipeline."""
    try:
        input_assignments = [
            RuntimeInputAssignment(
                tool_id=item.tool_id,
                requirement_type=item.requirement_type,
                total_input_size_mib=item.total_input_size_mib,
                compressed_input_size_mib=item.compressed_input_size_mib or 0.0,
                file_formats=item.file_formats or [],
            )
            for item in (request.input_assignments or [])
        ]

        if request.pipeline_id:
            pipeline = None
            if current_user:
                pipeline = get_pipeline_by_id(request.pipeline_id, current_user.id)
            if pipeline is None:
                pipeline = get_pipeline_by_id_public(request.pipeline_id)
            if pipeline is None:
                error_data = error_response(
                    error_code=ErrorCode.NOT_FOUND,
                    message="Pipeline not found for runtime estimation",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
                return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

            logger.info(f"[Estimator] Estimating runtime for pipeline {request.pipeline_id}: {len(pipeline.nodes or [])} nodes, {len(pipeline.edges or [])} edges")
            estimate = await run_in_threadpool(
                estimate_runtime_for_pipeline_graph,
                pipeline.nodes or [],
                pipeline.edges or [],
                request.vm_name,
                input_assignments,
            )
            logger.info(f"[Estimator] Estimate result: {estimate.estimated_price_usd} USD, {estimate.estimated_runtime_minutes} min, {len(estimate.tool_breakdown)} tools")
        elif request.tool_indices:
            estimate = await run_in_threadpool(
                estimate_runtime_for_tool_indices,
                request.tool_indices,
                request.vm_name,
                input_assignments,
            )
        else:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Provide either tool_indices or pipeline_id for runtime estimation",
                status_code=status.HTTP_400_BAD_REQUEST,
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

        return JSONResponse(
            content=success_response(
                data={
                    "model_type": estimate.model_type,
                    "vm_name": estimate.vm_name,
                    "vm_display_name": estimate.vm_display_name,
                    "partition_factor": estimate.partition_factor,
                    "vm_price_per_minute": estimate.vm_price_per_minute,
                    "total_input_size_mib": estimate.total_input_size_mib,
                    "estimated_runtime_seconds": estimate.estimated_runtime_seconds,
                    "estimated_runtime_minutes": estimate.estimated_runtime_minutes,
                    "estimated_runtime_hours": estimate.estimated_runtime_hours,
                    "estimated_price_usd": estimate.estimated_price_usd,
                    "fixed_overhead_minutes": estimate.fixed_overhead_minutes,
                    "execution_shape": estimate.execution_shape,
                    "tool_breakdown": estimate.tool_breakdown,
                    "assumptions": estimate.assumptions,
                },
                message="Runtime estimation completed",
                status_code=status.HTTP_200_OK,
            ),
            status_code=status.HTTP_200_OK,
        )
    except Exception as e:
        logger.error(f"Error estimating runtime: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to estimate runtime",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)
