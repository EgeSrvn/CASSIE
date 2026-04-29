"""
Job management routes for CASSIE backend.

This module provides:
- Create new jobs
- List user's jobs
- Get job details
- Update jobs
- Delete jobs
"""

from fastapi import APIRouter, Depends, HTTPException, status, Query, BackgroundTasks, Request
from fastapi.responses import JSONResponse
from typing import Optional, List, Dict, Any
from copy import deepcopy
from datetime import datetime
from pydantic import BaseModel, Field
import asyncio
import json
import time
# Use real JWT auth (Task 5.4 - now fixed)
from backend.api.routes.auth import get_current_user, get_auth_context, AuthContext
from backend.api.models.user_model import UserResponse
from backend.api.models.job_model import (
    JobCreate,
    JobUpdate,
    JobResponse,
    JobCreateResponse,
    JobStatus,
    JobExecutionResponse,
)
from backend.api.services.job_service import (
    create_job,
    get_job_by_id,
    get_jobs_by_user,
    update_job,
    delete_job,
    count_jobs_by_user
)
from backend.api.services.job_launch_service import (
    get_auto_start_payload,
    job_has_reserved_execution,
    start_job_execution_task,
)
from backend.api.services.output_retention_service import purge_expired_finished_job_outputs_for_user
from backend.api.services.user_limit_service import can_user_start_more_jobs, can_user_interact_with_job_outputs
from backend.api.services.vm_queue_service import get_vm_slot_usage, queue_or_start_job, reserve_vm_slot_for_job
from backend.api.services.job_execution_service import get_executions_by_job
from backend.api.services.billing_service import reserve_job_charge, settle_job_charge
from backend.api.services.kubernetes_manager import get_kubernetes_pipeline_runner, kubernetes_is_available
from backend.api.services.vm_partition_service import get_vm_partitions, get_vm_partition
from backend.api.utils.response_builder import (
    success_response,
    error_response,
    not_found_response,
    paginated_response,
    ErrorCode
)
from backend.api.utils.validators import (
    validate_job_name,
    validate_assembler,
    validate_data_types,
    validate_cloud_provider,
    validate_job_input
)
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_index, get_tool_registry
from backend.api.services.auth_service import create_job_upload_token

logger = get_logger(__name__)

router = APIRouter(prefix="/jobs", tags=["jobs"])


class PipelinePlanInput(BaseModel):
    id: Optional[int] = None
    binding_id: Optional[str] = None
    tool_id: Optional[str] = None
    requirement_type: Optional[str] = None
    label: Optional[str] = None
    filename: str
    file_format: Optional[str] = None
    size_bytes: int = 0
    s3_key: Optional[str] = None
    source: Optional[str] = None


class PipelinePlanPreviewRequest(BaseModel):
    tool_indices: Optional[List[int]] = None
    pipeline_id: Optional[int] = None
    input_file_ids: Optional[List[int]] = None
    planned_inputs: Optional[List[PipelinePlanInput]] = None
    execution_preferences: Optional[Dict[str, Any]] = None


def _job_response_for_user(job, username: Optional[str]) -> dict:
    interactive_outputs_enabled, _ = can_user_interact_with_job_outputs(
        user_id=job.user_id,
        username=username,
        job_id=job.id,
        job_status=job.status.value if hasattr(job.status, "value") else str(job.status),
    )

    return JobResponse(
        id=job.id,
        user_id=job.user_id,
        name=job.name,
        status=job.status,
        workflow_id=job.workflow_id,
        pipeline_config_id=job.pipeline_config_id,
        pipeline_id=job.pipeline_id,
        assembler=job.assembler,
        data_types=job.data_types,
        cloud_provider=job.cloud_provider,
        execution_preferences=job.execution_preferences,
        vm_name=job.vm_name,
        estimated_price_usd=getattr(job, "estimated_price_usd", 0.0),
        max_charge_usd=getattr(job, "max_charge_usd", 0.0),
        actual_price_charged_usd=getattr(job, "actual_price_charged_usd", None),
        balance_reserved_at=getattr(job, "balance_reserved_at", None),
        balance_charged_at=getattr(job, "balance_charged_at", None),
        created_at=job.created_at,
        updated_at=job.updated_at,
        interactive_outputs_enabled=interactive_outputs_enabled,
    ).model_dump(mode='json')


def _cleanup_deleted_job_resources(
    *,
    job_id: int,
    user_id: int,
    username: str,
    file_s3_keys: List[str],
    executions: List,
) -> None:
    from backend.api.services.minio_client import get_minio_client

    k8s_cleanup_summary: Dict[str, Any] = {
        "namespace": None,
        "deleted_stage_jobs": [],
        "errors": [],
    }

    if kubernetes_is_available():
        try:
            k8s_cleanup_summary = get_kubernetes_pipeline_runner().terminate_job_stages(job_id, executions)
        except Exception as cleanup_error:
            logger.warning(
                f"Failed to terminate Kubernetes stages for deleted job {job_id}: {cleanup_error}",
                exc_info=True,
            )
            k8s_cleanup_summary["errors"].append(str(cleanup_error))

    minio_client = get_minio_client()
    deleted_objects = 0

    for s3_key in file_s3_keys:
        try:
            minio_client.delete_file(
                user_id=user_id,
                s3_key=s3_key,
                username=username,
            )
            deleted_objects += 1
        except Exception as cleanup_error:
            logger.warning(
                f"Failed to delete MinIO object for deleted job {job_id}, key {s3_key}: {cleanup_error}",
                exc_info=True,
            )

    try:
        deleted_objects += minio_client.delete_prefix(
            user_id=user_id,
            prefix=f"jobs/{job_id}/",
            username=username,
        )
    except Exception as cleanup_error:
        logger.warning(
            f"Failed to delete MinIO job prefix for deleted job {job_id}: {cleanup_error}",
            exc_info=True,
        )

    logger.info(
        "Finished asynchronous cleanup for deleted job %s. Deleted objects=%s, kubernetes_cleanup=%s",
        job_id,
        deleted_objects,
        k8s_cleanup_summary,
    )


def _infer_file_formats(file_record) -> set[str]:
    """Infer normalized file formats from stored metadata and filename."""
    formats: set[str] = set()
    file_format = getattr(file_record, "file_format", None)
    if file_format:
        formats.add(str(file_format).lower().strip().lstrip("."))

    filename = str(getattr(file_record, "filename", "") or "").lower()
    if filename.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq")):
        formats.add("fastq")
    if filename.endswith((".fasta.gz", ".fa.gz", ".fna.gz", ".fasta", ".fa", ".fna")):
        formats.add("fasta")
    if filename.endswith(".gff3"):
        formats.update({"gff", "gff3"})
    if filename.endswith(".gff"):
        formats.add("gff")
    if filename.endswith(".gtf"):
        formats.add("gtf")
    if filename.endswith(".hal"):
        formats.add("hal")
    if filename.endswith(".gfa"):
        formats.add("gfa")
    if filename.endswith((".cfg", ".conf", ".ini")):
        formats.update({"cfg", "conf", "ini"})
    if filename.endswith(".json"):
        formats.add("json")
    if filename.endswith(".txt"):
        formats.add("txt")
    if filename.endswith((".meryl", ".meryl.tar", ".meryl.tar.gz", ".meryl.tgz")):
        formats.add("meryl")
    if filename.endswith(".tgz"):
        formats.add("tgz")
    if filename.endswith((".tar", ".tar.gz")):
        formats.add("tar")

    return formats


def _validate_job_inputs_against_first_tool(job, input_files) -> Optional[str]:
    """Validate direct job inputs before launching Kubernetes for tool-based jobs."""
    if not job.tool_indices:
        return None

    first_tool = get_tool_by_index(job.tool_indices[0])
    if not first_tool:
        return None

    input_formats_by_file = {
        getattr(file_record, "filename", "input file"): _infer_file_formats(file_record)
        for file_record in input_files
    }

    for requirement in first_tool.get("input_requirements", []):
        accepted_formats = {
            str(format_name).lower().strip().lstrip(".")
            for format_name in requirement.get("formats", [])
            if str(format_name).strip()
        }
        if not accepted_formats:
            continue

        has_matching_file = any(
            accepted_formats.intersection(file_formats)
            for file_formats in input_formats_by_file.values()
        )
        if has_matching_file:
            continue

        accepted_label = ", ".join(sorted(accepted_formats)).upper()
        selected_files = ", ".join(input_formats_by_file.keys()) or "none"
        return (
            f"{first_tool.get('name', 'Selected tool')} requires {requirement.get('label', 'input files')} "
            f"({accepted_label}). Selected files: {selected_files}."
        )

    return None


def _sanitize_execution_message(message: Optional[str]) -> Optional[str]:
    """Return a concise user-facing execution message without raw tool logs."""
    if not message:
        return message

    text = str(message).strip()
    if not text:
        return None

    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    if not first_line:
        return None

    return first_line[:500] + ("..." if len(first_line) > 500 else "")


def _sanitize_execution_parameters(parameters_used: Optional[Dict]) -> Optional[Dict]:
    """Hide internal log previews while keeping stage progress metadata."""
    if not isinstance(parameters_used, dict):
        return parameters_used

    sanitized = deepcopy(parameters_used)
    stages = sanitized.get("stages")
    if isinstance(stages, list):
        cleaned_stages = []
        for stage in stages:
            if isinstance(stage, dict):
                cleaned = dict(stage)
                cleaned.pop("logs_preview", None)
                if "error" in cleaned:
                    cleaned["error"] = _sanitize_execution_message(cleaned.get("error"))
                cleaned_stages.append(cleaned)
            else:
                cleaned_stages.append(stage)
        sanitized["stages"] = cleaned_stages

    return sanitized


def _merge_runtime_stage_details(runtime_details: Optional[Dict[str, Any]]) -> Dict[int, Dict[tuple[Any, Any], Dict[str, Any]]]:
    if not isinstance(runtime_details, dict):
        return {}

    runtime_stages = runtime_details.get("stages")
    if not isinstance(runtime_stages, list):
        return {}

    merged: Dict[int, Dict[tuple[Any, Any], Dict[str, Any]]] = {}
    for runtime_stage in runtime_stages:
        if not isinstance(runtime_stage, dict):
            continue
        execution_id = runtime_stage.get("execution_id")
        if not isinstance(execution_id, int):
            continue
        key = (
            runtime_stage.get("stage_number"),
            str(runtime_stage.get("tool_id") or "").strip().upper(),
        )
        merged.setdefault(execution_id, {})[key] = runtime_stage
    return merged


def _purge_expired_outputs_safely(user_id: int, username: Optional[str]) -> None:
    try:
        purge_expired_finished_job_outputs_for_user(user_id, username)
    except Exception as cleanup_error:
        logger.warning(
            f"Failed to reconcile expired output retention for user {user_id}: {cleanup_error}",
            exc_info=True,
        )


@router.get("/vms")
async def list_available_vms(
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List available virtual machines for job execution.
    
    Returns:
        List of available VM names
    """
    try:
        runner = get_kubernetes_pipeline_runner()
        vms = runner.get_vm_capacity_summary()
        
        return JSONResponse(
            content=success_response(
                data=vms,
                message="Available VMs retrieved successfully",
                status_code=status.HTTP_200_OK
            ),
            status_code=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Error listing VMs: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve available VMs",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_job_endpoint(
    job_data: JobCreate,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Create a new job.
    
    Args:
        job_data: Job creation data
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with created job data
    """
    # Log parsed job data for debugging
    logger.info(f"[JOB CREATE] Received job data: name='{job_data.name}', workflow_id={job_data.workflow_id}, tool_indices={job_data.tool_indices}, pipeline_id={job_data.pipeline_id}, data_types={job_data.data_types}, assembler={job_data.assembler}, cloud_provider={job_data.cloud_provider}")
    logger.info(f"[JOB CREATE] Full job_data model: {job_data.model_dump()}")

    selected_data_file_ids = list(job_data.input_file_ids or [])
    selected_staged_file_ids = list(job_data.staged_input_file_ids or [])
    selected_input_file_ids = selected_data_file_ids + selected_staged_file_ids
    
    # Validate input
    is_valid, error_msg = validate_job_name(job_data.name)
    if not is_valid:
        logger.warning(f"Job name validation failed: {error_msg}")
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if job_data.assembler:
        is_valid, error_msg = validate_assembler(job_data.assembler)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    available_vm_partitions = get_vm_partitions()
    if job_data.vm_name:
        selected_vm = get_vm_partition(job_data.vm_name)
        if selected_vm is None:
            valid_vm_names = ", ".join(partition.name for partition in available_vm_partitions)
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Invalid vm_name '{job_data.vm_name}'. Valid VM names: {valid_vm_names}",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    elif available_vm_partitions:
        job_data.vm_name = available_vm_partitions[0].name
    
    if job_data.data_types:
        is_valid, error_msg = validate_data_types(job_data.data_types)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if job_data.cloud_provider:
        is_valid, error_msg = validate_cloud_provider(job_data.cloud_provider.value)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    if job_data.pending_upload_count is not None and job_data.expected_total_input_files is not None:
        if job_data.expected_total_input_files < job_data.pending_upload_count:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="expected_total_input_files must be greater than or equal to pending_upload_count",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Validate tool selection, workflow_id, or pipeline_id
    if job_data.tool_indices and job_data.pipeline_id:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message="Cannot specify both tool_indices and pipeline_id. Use one or the other.",
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if job_data.tool_indices:
        logger.info(f"Validating tool_indices: {job_data.tool_indices}")
        if len(job_data.tool_indices) == 0:
            logger.warning("Tool indices validation failed: empty list")
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="At least one tool must be selected",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
        invalid_indices = [idx for idx in job_data.tool_indices if get_tool_by_index(idx) is None]
        if invalid_indices:
            max_index = max(len(get_tool_registry()) - 1, 0)
            logger.warning(f"Tool index validation failed: {invalid_indices} are out of range")
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=(
                    f"Invalid tool index or indices: {', '.join(str(idx) for idx in invalid_indices)}. "
                    f"Valid indices are 0-{max_index}."
                ),
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    elif not job_data.workflow_id or job_data.workflow_id == 0:
        if not job_data.pipeline_id:
            logger.warning(f"Validation failed: Neither workflow_id ({job_data.workflow_id}), tool_indices ({job_data.tool_indices}), nor pipeline_id ({job_data.pipeline_id}) provided")
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Either workflow_id, tool_indices, or pipeline_id must be provided",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Combined validation
    is_valid, error_msg = validate_job_input(
        name=job_data.name,
        assembler=job_data.assembler,
        data_types=job_data.data_types,
        cloud_provider=job_data.cloud_provider.value if job_data.cloud_provider else None
    )
    if not is_valid:
        logger.warning(f"Combined validation failed: {error_msg}")
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=error_msg,
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

    should_reserve_vm_slot = bool(
        len(selected_input_file_ids) > 0
        or (job_data.pending_upload_count and job_data.pending_upload_count > 0)
    )

    if should_reserve_vm_slot:
        can_start_more, current_active_jobs, max_active_jobs = can_user_start_more_jobs(
            user_id=current_user.id,
            username=current_user.username,
        )
        if not can_start_more:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=(
                    f"You already have {current_active_jobs} active jobs. "
                    f"The limit is {max_active_jobs}."
                ),
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

        vm_slot_usage = get_vm_slot_usage(job_data.vm_name)
        if vm_slot_usage["available_job_slots"] <= 0:
            selected_vm = get_vm_partition(job_data.vm_name)
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=(
                    f"{selected_vm.display_name if selected_vm else job_data.vm_name} has no available job slots right now. "
                    "Choose another VM or wait for an active job to finish."
                ),
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Create job
    try:
        logger.info(f"[JOB CREATE] Calling create_job with user_id={current_user.id}, pipeline_id={job_data.pipeline_id}")
        job = create_job(current_user.id, job_data)
        logger.info(f"[JOB CREATE] Job created successfully: id={job.id}, workflow_id={job.workflow_id}, pipeline_id={job.pipeline_id}")

        if should_reserve_vm_slot:
            try:
                reserve_vm_slot_for_job(
                    job_id=job.id,
                    user_id=current_user.id,
                    workflow_id=job.workflow_id,
                    input_file_ids=selected_input_file_ids,
                    vm_name=job.vm_name,
                )
                reserve_job_charge(
                    job_id=job.id,
                    user_id=current_user.id,
                    estimated_price_usd=job_data.estimated_price_usd or 0,
                )
                job = get_job_by_id(job.id, current_user.id) or job
            except Exception:
                delete_job(job.id, current_user.id)
                raise
        
        # Link pre-uploaded files to this job if provided
        # Handle both staging files and data library files
        input_file_ids = []
        if selected_data_file_ids or selected_staged_file_ids:
            from backend.api.services.storage_service import get_file_by_id, update_file
            from backend.api.services.data_file_service import get_data_file_by_id, copy_data_file_to_job
            from backend.api.models.pipeline_model import FileUpdate
            
            logger.info(
                f"[JOB CREATE] Processing {len(selected_data_file_ids)} data library file(s) and "
                f"{len(selected_staged_file_ids)} staged file(s) for job {job.id}"
            )
            for file_id in selected_data_file_ids:
                # Check if file is from data library (can be in folder or root)
                data_file = get_data_file_by_id(file_id, current_user.id)
                if data_file:
                    # Copy data library file to job (whether in folder or root)
                    logger.info(f"[JOB CREATE] Copying data library file {file_id} (folder_id={data_file.folder_id}) to job {job.id}")
                    copied_file = copy_data_file_to_job(file_id, current_user.id, job.id)
                    if copied_file:
                        input_file_ids.append(copied_file.id)
                        logger.info(f"[JOB CREATE] Copied file {file_id} to job {job.id} as file {copied_file.id}")
                    else:
                        logger.warning(f"[JOB CREATE] Failed to copy data library file {file_id}")
                else:
                    # File is a staging file or already a job file, link it to this job
                    file_record = get_file_by_id(file_id, user_id=current_user.id)
                    if file_record:
                        # Update file to link it to this job
                        update_data = FileUpdate(job_id=job.id)
                        updated_file = update_file(file_id, current_user.id, update_data)
                        if updated_file:
                            input_file_ids.append(file_id)
                            logger.info(f"[JOB CREATE] Linked file {file_id} to job {job.id}")
                        else:
                            logger.warning(f"[JOB CREATE] Failed to link file {file_id} to job {job.id}")
                    else:
                        logger.warning(f"[JOB CREATE] File {file_id} not found or doesn't belong to user {current_user.id}")

            for file_id in selected_staged_file_ids:
                file_record = get_file_by_id(file_id, user_id=current_user.id)
                if file_record:
                    update_data = FileUpdate(job_id=job.id)
                    updated_file = update_file(file_id, current_user.id, update_data)
                    if updated_file:
                        input_file_ids.append(file_id)
                        logger.info(f"[JOB CREATE] Linked staged file {file_id} to job {job.id}")
                    else:
                        logger.warning(f"[JOB CREATE] Failed to link staged file {file_id} to job {job.id}")
                else:
                    logger.warning(f"[JOB CREATE] Staged file {file_id} not found or doesn't belong to user {current_user.id}")
        
        # Job creation complete - status is PENDING
        # User must manually execute the job via POST /jobs/{job_id}/execute
        logger.info(
            f"Job {job.id} created successfully with status PENDING. "
            f"Input files: {len(input_file_ids) if input_file_ids else 0}. "
            f"User must manually trigger execution via the execute endpoint."
        )
        
        upload_session_token: Optional[str] = None
        if job_data.pending_upload_count and job_data.pending_upload_count > 0:
            upload_session_token = create_job_upload_token(
                data={
                    "user_id": current_user.id,
                    "username": current_user.username,
                    "job_id": job.id,
                    "expected_total_input_files": job_data.expected_total_input_files,
                }
            )

        return JSONResponse(
            content=success_response(
                data=JobCreateResponse(
                    id=job.id,
                    user_id=job.user_id,
                    name=job.name,
                    status=job.status,
                    workflow_id=job.workflow_id,
                    pipeline_config_id=job.pipeline_config_id,
                    pipeline_id=job.pipeline_id,
                    assembler=job.assembler,
                    data_types=job.data_types,
                    cloud_provider=job.cloud_provider,
                    execution_preferences=job.execution_preferences,
                    vm_name=job.vm_name,
                    estimated_price_usd=getattr(job, "estimated_price_usd", 0.0),
                    max_charge_usd=getattr(job, "max_charge_usd", 0.0),
                    actual_price_charged_usd=getattr(job, "actual_price_charged_usd", None),
                    balance_reserved_at=getattr(job, "balance_reserved_at", None),
                    balance_charged_at=getattr(job, "balance_charged_at", None),
                    created_at=job.created_at,
                    updated_at=job.updated_at,
                    upload_session_token=upload_session_token,
                    pending_upload_count=job_data.pending_upload_count,
                    expected_total_input_files=job_data.expected_total_input_files,
                    interactive_outputs_enabled=True,
                ).model_dump(mode='json'),  # Use mode='json' to serialize datetime to ISO strings
                message="Job created successfully",
                status_code=status.HTTP_201_CREATED
            ),
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
        logger.error(f"Error creating job: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to create job",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("")
async def list_jobs(
    background_tasks: BackgroundTasks,
    status_filter: Optional[JobStatus] = Query(None, alias="status", description="Filter by job status"),
    page: int = Query(1, ge=1, description="Page number"),
    per_page: int = Query(20, ge=1, le=100, description="Items per page"),
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List user's jobs with optional status filter and pagination.
    
    Args:
        status_filter: Optional status filter
        page: Page number (1-indexed)
        per_page: Number of items per page
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Paginated response with list of jobs
    """
    try:
        background_tasks.add_task(
            _purge_expired_outputs_safely,
            current_user.id,
            current_user.username,
        )

        offset = (page - 1) * per_page
        jobs = get_jobs_by_user(
            user_id=current_user.id,
            status=status_filter,
            limit=per_page,
            offset=offset
        )
        
        total = count_jobs_by_user(current_user.id, status_filter)
        
        job_responses = [_job_response_for_user(job, current_user.username) for job in jobs]
        
        return paginated_response(
            data=job_responses,
            page=page,
            per_page=per_page,
            total=total,
            message="Jobs retrieved successfully"
        )
    except Exception as e:
        logger.error(f"Error listing jobs: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve jobs",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{job_id}")
async def get_job(
    job_id: int,
    auth_context: AuthContext = Depends(get_auth_context)
):
    """
    Get job details by ID.
    
    Args:
        job_id: Job ID
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with job data
    """
    if auth_context.token_type == "job_upload_session" and auth_context.job_id != job_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upload session token cannot access this job")

    current_user = auth_context.user
    job = get_job_by_id(job_id, user_id=current_user.id)
    
    if job is None:
        error_data = not_found_response("Job", job_id)
        return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
    
    return success_response(
        data=_job_response_for_user(job, current_user.username),
        message="Job retrieved successfully"
    )


@router.get("/{job_id}/pipeline-visualization", status_code=status.HTTP_200_OK)
async def get_job_pipeline_visualization(
    job_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """Return the executable pipeline graph for a job with live block statuses."""
    try:
        job = get_job_by_id(job_id, user_id=current_user.id)
        if not job:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

        payload = get_kubernetes_pipeline_runner().get_job_pipeline_visualization(
            job_id=job_id,
            user_id=current_user.id,
        )
        return JSONResponse(
            content=success_response(
                data=payload,
                message="Job pipeline visualization retrieved successfully",
                status_code=status.HTTP_200_OK,
            ),
            status_code=status.HTTP_200_OK,
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error building pipeline visualization for job {job_id}: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to build job pipeline visualization",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/pipeline-plan-preview", status_code=status.HTTP_200_OK)
async def preview_pipeline_plan(
    request: PipelinePlanPreviewRequest,
    current_user: UserResponse = Depends(get_current_user)
):
    """Return a backend-generated pipeline visualization without creating or executing a job."""
    try:
        payload = get_kubernetes_pipeline_runner().build_pipeline_plan_preview(
            user_id=current_user.id,
            tool_indices=request.tool_indices,
            pipeline_id=request.pipeline_id,
            input_file_ids=request.input_file_ids,
            planned_inputs=[
                item.model_dump(exclude_none=True)
                for item in (request.planned_inputs or [])
            ],
            execution_preferences=request.execution_preferences,
        )
        return JSONResponse(
            content=success_response(
                data=payload,
                message="Pipeline plan preview created successfully",
                status_code=status.HTTP_200_OK,
            ),
            status_code=status.HTTP_200_OK,
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error building pipeline plan preview: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to build pipeline plan preview",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.post("/{job_id}/execute", status_code=status.HTTP_200_OK)
async def execute_job(
    job_id: int,
    background_tasks: BackgroundTasks,
    auth_context: AuthContext = Depends(get_auth_context)
):
    """
    Manually execute a pending job.
    
    Args:
        job_id: Job ID to execute
        background_tasks: Background tasks handler
        current_user: Current authenticated user
        
    Returns:
        Success response with execution details
    """
    try:
        if auth_context.token_type == "job_upload_session" and auth_context.job_id != job_id:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Upload session token cannot execute this job")

        current_user = auth_context.user
        # Verify job exists and belongs to user
        job = get_job_by_id(job_id, user_id=current_user.id)
        if not job:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        if job.status == JobStatus.RUNNING:
            executions = get_executions_by_job(job_id)
            waiting_checkpoint_execution = next(
                (
                    execution
                    for execution in executions
                    if execution.status.value == "running"
                    and any(
                        isinstance(stage, dict)
                        and str(stage.get("status") or "").strip().lower() == "waiting_for_checkpoint"
                        for stage in (execution.parameters_used or {}).get("stages", [])
                    )
                ),
                None,
            )
            if waiting_checkpoint_execution is None:
                error_data = error_response(
                    error_code=ErrorCode.VALIDATION_ERROR,
                    message=f"Job must be in PENDING status to execute. Current status: {job.status.value}",
                    status_code=status.HTTP_400_BAD_REQUEST
                )
                return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

            resume_result = get_kubernetes_pipeline_runner().resume_execution_from_checkpoint(job_id, current_user.id)
            return success_response(
                data={
                    "job_id": job_id,
                    "status": "running",
                    "message": "Checkpointed pipeline branches resumed successfully",
                    "released_checkpoints": resume_result.get("released_checkpoints", []),
                },
                message="Checkpoint resumed successfully",
            )

        # Verify job is in PENDING status
        if job.status != JobStatus.PENDING:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Job must be in PENDING status to execute. Current status: {job.status.value}",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

        if not job_has_reserved_execution(job_id):
            can_start, current_running_jobs, max_running_jobs = can_user_start_more_jobs(
                user_id=current_user.id,
                username=current_user.username,
            )
            if not can_start:
                error_data = error_response(
                    error_code=ErrorCode.VALIDATION_ERROR,
                    message=(
                        f"You already have {current_running_jobs} active jobs. "
                        f"The limit is {max_running_jobs}."
                    ),
                    status_code=status.HTTP_400_BAD_REQUEST
                )
                return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
        
        _, input_file_ids, readiness_error = get_auto_start_payload(job_id, current_user.id)
        if readiness_error or not input_file_ids:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Cannot execute job: {readiness_error or 'Job is not ready to execute.'}",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)

        if getattr(job, "balance_reserved_at", None) is None:
            reserve_job_charge(
                job_id=job.id,
                user_id=current_user.id,
                estimated_price_usd=getattr(job, "estimated_price_usd", 0) or 0,
            )

        launch_result = await queue_or_start_job(
            job_id=job_id,
            user_id=current_user.id,
            workflow_id=job.workflow_id,
            input_file_ids=input_file_ids,
        )
        queue_position = launch_result.get("queue_position")
        queued = launch_result.get("state") == "queued"

        return success_response(
            data={
                "job_id": job_id,
                "status": "pending" if queued else "running",
                "queue_position": queue_position,
                "message": (
                    f"Job is queued on {job.vm_name} at position {queue_position}"
                    if queued
                    else "Job execution started successfully"
                ),
            },
            message="Job queued successfully" if queued else "Job execution started"
        )
    except ValueError as e:
        error_data = error_response(
            error_code=ErrorCode.VALIDATION_ERROR,
            message=str(e),
            status_code=status.HTTP_400_BAD_REQUEST
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    except Exception as e:
        logger.error(f"Error executing job: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to execute job",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.get("/{job_id}/executions", status_code=status.HTTP_200_OK)
async def list_job_executions(
    job_id: int,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    List execution attempts for a job, including backend-specific tracking data.
    """
    try:
        job = get_job_by_id(job_id, user_id=current_user.id)
        if not job:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

        from backend.api.services.job_execution_service import get_executions_by_job

        executions = get_executions_by_job(job_id)
        runtime_stage_lookup: Dict[int, Dict[tuple[Any, Any], Dict[str, Any]]] = {}
        try:
            runtime_stage_lookup = _merge_runtime_stage_details(
                get_kubernetes_pipeline_runner().get_job_runtime_details(job_id, executions)
            )
        except Exception as runtime_error:
            logger.warning("Failed to enrich runtime details for job %s: %s", job_id, runtime_error)

        payload = []
        for execution in executions:
            parameters_used = _sanitize_execution_parameters(execution.parameters_used)
            if isinstance(parameters_used, dict):
                stages = parameters_used.get("stages")
                if isinstance(stages, list):
                    runtime_lookup = runtime_stage_lookup.get(execution.id, {})
                    merged_stages = []
                    for stage in stages:
                        if not isinstance(stage, dict):
                            merged_stages.append(stage)
                            continue
                        merged_stage = dict(stage)
                        stage_key = (
                            merged_stage.get("stage_number"),
                            str(merged_stage.get("tool_id") or "").strip().upper(),
                        )
                        runtime_stage = runtime_lookup.get(stage_key) or {}
                        merged_stage["live_tool_logs"] = runtime_stage.get("live_tool_logs")
                        merged_stage["live_init_logs"] = runtime_stage.get("live_init_logs")
                        merged_stage["pod_phase"] = runtime_stage.get("pod_phase")
                        merged_stages.append(merged_stage)
                    parameters_used["stages"] = merged_stages

            payload.append(JobExecutionResponse(
                id=execution.id,
                job_id=execution.job_id,
                execution_number=execution.execution_number,
                status=execution.status,
                nextflow_run_id=execution.nextflow_run_id,
                work_dir=execution.work_dir,
                output_dir=execution.output_dir,
                process_id=execution.process_id,
                tool_versions=execution.tool_versions,
                parameters_used=parameters_used,
                error_message=_sanitize_execution_message(execution.error_message),
                started_at=execution.started_at,
                completed_at=execution.completed_at,
                created_at=execution.created_at
            ).model_dump(mode="json"))

        return JSONResponse(
            content=success_response(
                data=payload,
                message="Job executions retrieved successfully",
                status_code=status.HTTP_200_OK
            ),
            status_code=status.HTTP_200_OK
        )
    except Exception as e:
        logger.error(f"Error listing executions for job {job_id}: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to retrieve job executions",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


class AddFilesRequest(BaseModel):
    """Request model for adding files to a job."""
    file_ids: Optional[List[int]] = Field(None, description="List of data file IDs from data library (for tool-based jobs)")
    file_mappings: Optional[Dict[str, int]] = Field(None, description="Mapping of requirement type to file ID (for pipeline-based jobs, e.g., {'forward_reads': 1, 'reverse_reads': 2})")


@router.post("/{job_id}/files", status_code=status.HTTP_200_OK)
async def add_files_to_job(
    job_id: int,
    request: AddFilesRequest,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Add files from data library to a pending job.
    
    Args:
        job_id: Job ID to add files to
        file_ids: List of data file IDs from data library
        current_user: Current authenticated user
        
    Returns:
        Success response with updated job data
    """
    try:
        # Verify job exists and belongs to user
        job = get_job_by_id(job_id, user_id=current_user.id)
        if not job:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        # Verify job is in PENDING status
        if job.status != JobStatus.PENDING:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Files can only be added to jobs in PENDING status. Current status: {job.status.value}",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
        
        # Process files
        from backend.api.services.data_file_service import get_data_file_by_id, copy_data_file_to_job
        
        added_file_ids = []
        errors = []
        
        # Determine which files to add
        files_to_add: List[int] = []
        
        if request.file_mappings:
            # For pipeline-based jobs, use file mappings
            files_to_add = list(request.file_mappings.values())
        elif request.file_ids:
            # For tool-based jobs, use direct file IDs
            files_to_add = request.file_ids
        else:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message="Either file_ids or file_mappings must be provided",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
        
        for file_id in files_to_add:
            # Verify file exists and is from data library
            data_file = get_data_file_by_id(file_id, current_user.id)
            if not data_file:
                errors.append(f"File {file_id} not found or doesn't belong to user")
                continue
            
            if data_file.folder_id is None:
                errors.append(f"File {file_id} is not from data library (no folder_id)")
                continue
            
            # Copy file to job
            try:
                copied_file = copy_data_file_to_job(file_id, current_user.id, job_id)
                if copied_file:
                    added_file_ids.append(copied_file.id)
                    logger.info(f"Added file {file_id} to job {job_id} as file {copied_file.id}")
                else:
                    errors.append(f"Failed to copy file {file_id} to job")
            except Exception as e:
                logger.error(f"Error copying file {file_id} to job {job_id}: {e}", exc_info=True)
                errors.append(f"Error copying file {file_id}: {str(e)}")
        
        if not added_file_ids:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=f"Failed to add any files. Errors: {'; '.join(errors)}",
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
        
        # Reload job to get updated data
        updated_job = get_job_by_id(job_id, user_id=current_user.id)
        
        message = f"Successfully added {len(added_file_ids)} file(s) to job"
        if errors:
            message += f". Some files failed: {'; '.join(errors)}"

        ready_job, input_file_ids, readiness_error = get_auto_start_payload(job_id, current_user.id)
        if ready_job and input_file_ids:
            background_tasks.add_task(
                start_job_execution_task,
                ready_job.id,
                current_user.id,
                ready_job.workflow_id,
                input_file_ids,
            )
            message += ". Job started automatically."
        elif readiness_error:
            logger.info(f"Job {job_id} not auto-started after adding files: {readiness_error}")
        
        return success_response(
            data=JobResponse(
                id=updated_job.id,
                user_id=updated_job.user_id,
                name=updated_job.name,
                status=updated_job.status,
                workflow_id=updated_job.workflow_id,
                pipeline_config_id=updated_job.pipeline_config_id,
                pipeline_id=updated_job.pipeline_id,
                assembler=updated_job.assembler,
                data_types=updated_job.data_types,
                cloud_provider=updated_job.cloud_provider,
                execution_preferences=updated_job.execution_preferences,
                vm_name=updated_job.vm_name,
                created_at=updated_job.created_at,
                updated_at=updated_job.updated_at
            ).model_dump(mode='json'),
            message=message
        )
        
    except Exception as e:
        logger.error(f"Error adding files to job {job_id}: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message=f"Failed to add files to job: {str(e)}",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.put("/{job_id}")
async def update_job_endpoint(
    job_id: int,
    job_update: JobUpdate,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Update a job.
    
    Args:
        job_id: Job ID to update
        job_update: Job update data
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response with updated job data
    """
    # Validate input if provided
    if job_update.name is not None:
        is_valid, error_msg = validate_job_name(job_update.name)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if job_update.assembler is not None:
        is_valid, error_msg = validate_assembler(job_update.assembler)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if job_update.data_types is not None:
        is_valid, error_msg = validate_data_types(job_update.data_types)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    if job_update.cloud_provider is not None:
        is_valid, error_msg = validate_cloud_provider(job_update.cloud_provider.value)
        if not is_valid:
            error_data = error_response(
                error_code=ErrorCode.VALIDATION_ERROR,
                message=error_msg,
                status_code=status.HTTP_400_BAD_REQUEST
            )
            return JSONResponse(content=error_data, status_code=status.HTTP_400_BAD_REQUEST)
    
    # Update job
    try:
        job = update_job(job_id, current_user.id, job_update)
        
        if job is None:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)
        
        return success_response(
            data=JobResponse(
                id=job.id,
                user_id=job.user_id,
                name=job.name,
                status=job.status,
                workflow_id=job.workflow_id,
                pipeline_config_id=job.pipeline_config_id,
                pipeline_id=job.pipeline_id,
                assembler=job.assembler,
                data_types=job.data_types,
                cloud_provider=job.cloud_provider,
                execution_preferences=job.execution_preferences,
                vm_name=job.vm_name,
                created_at=job.created_at,
                updated_at=job.updated_at
            ).model_dump(mode='json'),  # Use mode='json' to serialize datetime to ISO strings
            message="Job updated successfully"
        )
    except Exception as e:
        logger.error(f"Error updating job: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to update job",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)


@router.delete("/{job_id}")
async def delete_job_endpoint(
    job_id: int,
    background_tasks: BackgroundTasks,
    current_user: UserResponse = Depends(get_current_user)
):
    """
    Delete a job.
    
    Args:
        job_id: Job ID to delete
        current_user: Current authenticated user (from dependency)
        
    Returns:
        Success response
    """
    try:
        job = get_job_by_id(job_id, user_id=current_user.id)
        if not job:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

        executions = get_executions_by_job(job_id)

        from backend.api.services.storage_service import get_files_by_user

        job_files = get_files_by_user(
            user_id=current_user.id,
            job_id=job_id,
            limit=1000,
            offset=0,
        )
        file_s3_keys = [file_record.s3_key for file_record in job_files if getattr(file_record, "s3_key", None)]

        try:
            settle_job_charge(job_id, current_user.id)
        except Exception as billing_error:
            logger.warning(f"Failed to settle billing before deleting job {job_id}: {billing_error}", exc_info=True)

        deleted = delete_job(job_id, current_user.id)
        
        if not deleted:
            error_data = not_found_response("Job", job_id)
            return JSONResponse(content=error_data, status_code=status.HTTP_404_NOT_FOUND)

        background_tasks.add_task(
            _cleanup_deleted_job_resources,
            job_id=job_id,
            user_id=current_user.id,
            username=current_user.username,
            file_s3_keys=file_s3_keys,
            executions=executions,
        )
        
        return success_response(
            data={
                "deleted_objects": len(file_s3_keys),
                "cleanup_queued": True,
            },
            message="Job and related data deleted successfully"
        )
    except Exception as e:
        logger.error(f"Error deleting job: {e}", exc_info=True)
        error_data = error_response(
            error_code=ErrorCode.INTERNAL_ERROR,
            message="Failed to delete job",
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR
        )
        return JSONResponse(content=error_data, status_code=status.HTTP_500_INTERNAL_SERVER_ERROR)

