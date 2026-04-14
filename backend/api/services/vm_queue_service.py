"""
VM job queue helpers.

Each VM partition exposes a fixed number of concurrent pipeline execution slots.
Jobs beyond that limit remain queued until a slot becomes available.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Optional

from backend.api.database.db_init import get_db_connection
from backend.api.models.job_model import (
    ExecutionStatus,
    JobExecutionCreate,
    JobExecutionUpdate,
    JobStatus,
    JobUpdate,
)
from backend.api.services.job_execution_service import create_job_execution, get_executions_by_job, update_job_execution
from backend.api.services.job_service import get_job_by_id, update_job
from backend.api.services.vm_partition_service import get_vm_partition, get_vm_partitions
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)

QUEUE_STATE_WAITING = "waiting_for_vm_slot"


def _next_execution_number(job_id: int) -> int:
    executions = get_executions_by_job(job_id)
    if not executions:
        return 1
    return max(int(execution.execution_number or 0) for execution in executions) + 1


def _base_parameters(
    *,
    workflow_id: int,
    input_files: List[int],
    vm_name: Optional[str],
) -> Dict[str, Any]:
    return {
        "backend": "kubernetes",
        "workflow_id": workflow_id,
        "input_files": list(input_files or []),
        "vm_name": vm_name,
        "stages": [],
    }


def _count_running_jobs_for_vm(vm_name: str) -> int:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT COUNT(DISTINCT e.job_id)
                FROM job_executions e
                JOIN jobs j ON j.id = e.job_id
                WHERE e.status = %s
                  AND j.status = %s
                  AND j.vm_name = %s
                """,
                (ExecutionStatus.RUNNING.value, JobStatus.RUNNING.value, vm_name),
            )
            row = cur.fetchone()
            return int(row[0] or 0) if row else 0
        finally:
            cur.close()


def get_vm_slot_usage(vm_name: str) -> Dict[str, int]:
    partition = get_vm_partition(vm_name)
    max_jobs = max(1, partition.max_jobs) if partition else 1
    running_jobs = _count_running_jobs_for_vm(vm_name)
    available_jobs = max(0, max_jobs - running_jobs)
    return {
        "max_jobs": max_jobs,
        "running_jobs": running_jobs,
        "available_job_slots": available_jobs,
    }


def _get_queued_execution_rows(vm_name: str) -> List[Dict[str, Any]]:
    with get_db_connection() as conn:
        cur = conn.cursor()
        try:
            cur.execute(
                """
                SELECT
                    e.id,
                    e.job_id,
                    e.execution_number,
                    e.parameters_used,
                    e.started_at,
                    j.user_id,
                    j.workflow_id,
                    j.status
                FROM job_executions e
                JOIN jobs j ON j.id = e.job_id
                WHERE e.status = %s
                  AND j.vm_name = %s
                ORDER BY e.created_at ASC, e.id ASC
                """,
                (ExecutionStatus.PENDING.value, vm_name),
            )

            queued: List[Dict[str, Any]] = []
            for row in cur.fetchall():
                parameters_used = row[3] or {}
                if not isinstance(parameters_used, dict):
                    continue
                queue_state = str(parameters_used.get("queue_state") or "").strip().lower()
                if queue_state != QUEUE_STATE_WAITING:
                    continue
                queued.append(
                    {
                        "execution_id": int(row[0]),
                        "job_id": int(row[1]),
                        "execution_number": int(row[2]),
                        "parameters_used": parameters_used,
                        "started_at": row[4],
                        "user_id": int(row[5]),
                        "workflow_id": int(row[6]),
                        "job_status": str(row[7] or ""),
                    }
                )
            return queued
        finally:
            cur.close()


def _queue_position(vm_name: str, execution_id: Optional[int] = None) -> int:
    queued = _get_queued_execution_rows(vm_name)
    if execution_id is None:
        return len(queued) + 1
    for index, row in enumerate(queued, start=1):
        if row["execution_id"] == execution_id:
            return index
    return len(queued) + 1


def _refresh_queue_positions(vm_name: str) -> None:
    queued = _get_queued_execution_rows(vm_name)
    for index, row in enumerate(queued, start=1):
        parameters_used = dict(row["parameters_used"] or {})
        parameters_used["queue_state"] = QUEUE_STATE_WAITING
        parameters_used["queue_position"] = index
        parameters_used["queued_vm_name"] = vm_name
        update_job_execution(
            row["execution_id"],
            JobExecutionUpdate(parameters_used=parameters_used),
        )


def _find_existing_active_or_queued_execution(job_id: int):
    executions = get_executions_by_job(job_id)
    for execution in executions:
        if execution.status in {ExecutionStatus.RUNNING, ExecutionStatus.PENDING}:
            return execution
    return None


async def queue_or_start_job(
    *,
    job_id: int,
    user_id: int,
    workflow_id: int,
    input_file_ids: List[int],
) -> Dict[str, Any]:
    from backend.api.services.kubernetes_manager import get_pipeline_runner

    job = get_job_by_id(job_id, user_id=user_id)
    if not job:
        raise ValueError(f"Job {job_id} not found")

    selected_vm = get_vm_partition(job.vm_name) or get_vm_partitions()[0]
    existing_execution = _find_existing_active_or_queued_execution(job_id)
    if existing_execution:
        parameters_used = getattr(existing_execution, "parameters_used", None) or {}
        if existing_execution.status == ExecutionStatus.RUNNING:
            return {
                "state": "running",
                "execution_id": existing_execution.id,
                "queue_position": None,
            }
        if str(parameters_used.get("queue_state") or "").strip().lower() == QUEUE_STATE_WAITING:
            position = _queue_position(selected_vm.name, existing_execution.id)
            if parameters_used.get("queue_position") != position:
                parameters_used["queue_position"] = position
                update_job_execution(
                    existing_execution.id,
                    JobExecutionUpdate(parameters_used=parameters_used),
                )
            return {
                "state": "queued",
                "execution_id": existing_execution.id,
                "queue_position": position,
            }
        return {
            "state": "queued",
            "execution_id": existing_execution.id,
            "queue_position": parameters_used.get("queue_position"),
        }

    running_count = _count_running_jobs_for_vm(selected_vm.name)
    if running_count < selected_vm.max_jobs:
        runner = get_pipeline_runner()
        execution = await runner.start_pipeline(
            job_id=job_id,
            user_id=user_id,
            workflow_id=workflow_id,
            input_files=input_file_ids,
            execution_number=_next_execution_number(job_id),
            vm_name=selected_vm.name,
        )
        return {
            "state": "running",
            "execution_id": execution.get("execution_id"),
            "queue_position": None,
        }

    position = _queue_position(selected_vm.name)
    parameters_used = _base_parameters(
        workflow_id=workflow_id,
        input_files=input_file_ids,
        vm_name=selected_vm.name,
    )
    parameters_used.update(
        {
            "queue_state": QUEUE_STATE_WAITING,
            "queue_position": position,
            "queued_vm_name": selected_vm.name,
            "queued_at": datetime.now().isoformat(),
        }
    )
    execution = create_job_execution(
        JobExecutionCreate(
            job_id=job_id,
            execution_number=_next_execution_number(job_id),
            status=ExecutionStatus.PENDING,
            nextflow_run_id=None,
            work_dir=None,
            output_dir=None,
            process_id=None,
            tool_versions={},
            parameters_used=parameters_used,
            started_at=None,
        )
    )
    update_job(job_id, user_id, JobUpdate(status=JobStatus.PENDING))
    _refresh_queue_positions(selected_vm.name)
    logger.info(
        "Queued job %s on %s at position %s (execution %s)",
        job_id,
        selected_vm.name,
        position,
        execution.id,
    )
    return {
        "state": "queued",
        "execution_id": execution.id,
        "queue_position": position,
    }


async def schedule_queued_jobs(vm_name: Optional[str] = None) -> int:
    from backend.api.services.kubernetes_manager import get_pipeline_runner

    started = 0
    partitions = [get_vm_partition(vm_name)] if vm_name else get_vm_partitions()
    partitions = [partition for partition in partitions if partition is not None]

    for partition in partitions:
        if partition is None:
            continue

        while _count_running_jobs_for_vm(partition.name) < partition.max_jobs:
            queued = _get_queued_execution_rows(partition.name)
            if not queued:
                break

            next_item = queued[0]
            if next_item["job_status"] != JobStatus.PENDING.value:
                update_job_execution(
                    next_item["execution_id"],
                    JobExecutionUpdate(
                        status=ExecutionStatus.CANCELLED,
                        error_message="Queued execution discarded because the job is no longer pending.",
                        completed_at=datetime.now(),
                    ),
                )
                _refresh_queue_positions(partition.name)
                continue

            runner = get_pipeline_runner()
            await runner.start_pipeline(
                job_id=next_item["job_id"],
                user_id=next_item["user_id"],
                workflow_id=next_item["workflow_id"],
                input_files=list(next_item["parameters_used"].get("input_files") or []),
                execution_number=next_item["execution_number"],
                execution_id=next_item["execution_id"],
                parameters_used=next_item["parameters_used"],
                vm_name=partition.name,
            )
            started += 1
            _refresh_queue_positions(partition.name)

    return started
