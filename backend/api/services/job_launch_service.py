"""
Helpers for deciding when a pending job can start and launching it.
"""

from typing import List, Optional, Tuple

from backend.api.models.job_model import JobStatus, JobUpdate
from backend.api.models.pipeline_model import FileType
from backend.api.services.job_execution_service import get_executions_by_job
from backend.api.services.job_service import get_job_by_id, update_job
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_index

logger = get_logger(__name__)


def _infer_file_formats(file_record) -> set[str]:
    formats: set[str] = set()
    file_format = getattr(file_record, "file_format", None)
    if file_format:
        formats.add(str(file_format).lower().strip().lstrip("."))

    filename = str(getattr(file_record, "filename", "") or "").lower()
    if filename.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq")):
        formats.add("fastq")
    if filename.endswith((".fasta.gz", ".fa.gz", ".fna.gz", ".fasta", ".fa", ".fna")):
        formats.add("fasta")

    return formats


def _validate_job_inputs_against_first_tool(job, input_files) -> Optional[str]:
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


def job_has_active_execution(job_id: int) -> bool:
    from backend.api.models.job_model import ExecutionStatus

    executions = get_executions_by_job(job_id)
    return any(execution.status == ExecutionStatus.RUNNING for execution in executions)


def get_job_execution_readiness(job, user_id: int) -> Tuple[List[int], Optional[str]]:
    from backend.api.services.pipeline_analyzer import analyze_pipeline_requirements
    from backend.api.services.pipeline_service import get_pipeline_by_id
    from backend.api.services.storage_service import get_files_by_user

    input_files = get_files_by_user(
        user_id=user_id,
        job_id=job.id,
        file_type=FileType.INPUT,
        limit=100,
        offset=0,
    )
    input_file_ids = [file_record.id for file_record in input_files]

    if job.pipeline_id:
        pipeline = get_pipeline_by_id(job.pipeline_id, user_id)
        if pipeline:
            requirements = analyze_pipeline_requirements(pipeline)
            required_count = len(requirements.get("input_requirements", []))
            if required_count > 0 and len(input_file_ids) < required_count:
                missing_count = required_count - len(input_file_ids)
                return input_file_ids, (
                    f"Missing {missing_count} required input file(s). "
                    f"This pipeline requires {required_count} input file(s), but only {len(input_file_ids)} file(s) are provided."
                )

    if not input_file_ids:
        return input_file_ids, "No input files found. Please upload input files first."

    input_validation_error = _validate_job_inputs_against_first_tool(job, input_files)
    if input_validation_error:
        return input_file_ids, input_validation_error

    return input_file_ids, None


async def start_job_execution_task(job_id: int, user_id: int, workflow_id: int, input_file_ids: List[int]) -> None:
    from backend.api.services.vm_queue_service import queue_or_start_job

    try:
        logger.info(f"Starting or queueing pipeline execution for job {job_id}")
        result = await queue_or_start_job(
            job_id=job_id,
            user_id=user_id,
            workflow_id=workflow_id,
            input_file_ids=input_file_ids,
        )
        logger.info(
            "Pipeline execution decision for job %s: state=%s execution_id=%s queue_position=%s",
            job_id,
            result.get("state"),
            result.get("execution_id"),
            result.get("queue_position"),
        )
    except Exception as exc:
        logger.error(f"Error starting pipeline for job {job_id}: {exc}", exc_info=True)
        update_job(job_id, user_id, JobUpdate(status=JobStatus.FAILED))


def get_auto_start_payload(job_id: int, user_id: int) -> Tuple[Optional[object], Optional[List[int]], Optional[str]]:
    job = get_job_by_id(job_id, user_id=user_id)
    if not job:
        return None, None, "Job not found"

    if job.status != JobStatus.PENDING:
        return job, None, f"Job is not pending (status: {job.status.value})"

    if job_has_active_execution(job_id):
        return job, None, "Job already has an active execution"

    input_file_ids, readiness_error = get_job_execution_readiness(job, user_id)
    if readiness_error:
        return job, None, readiness_error

    return job, input_file_ids, None
