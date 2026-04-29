"""
Kubernetes-based pipeline execution for CASSIE.

This runner executes each selected bioinformatics tool as a Kubernetes Job.
Inputs are downloaded from MinIO into the pod by an init container, the tool
container writes to a shared workspace, and a lightweight helper container keeps
the pod alive long enough for the backend to copy results back out with
``kubectl cp`` before the Job is deleted.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import subprocess
import tarfile
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from backend.api.models.job_model import (
    ExecutionStatus,
    JobExecutionCreate,
    JobExecutionUpdate,
    JobStatus,
    JobUpdate,
)
from backend.api.models.pipeline_model import FileCreate, FileType
from backend.api.services.job_execution_service import create_job_execution, get_running_executions, update_job_execution
from backend.api.services.job_archive_service import prewarm_job_outputs_zip
from backend.api.services.job_service import update_job, get_job_by_id
from backend.api.services.billing_service import settle_job_charge
from backend.api.services.minio_client import get_minio_client
from backend.api.services.runtime_training_logger import append_successful_tool_training_rows
from backend.api.services.storage_service import create_file_record, get_file_by_id, get_files_by_user
from backend.api.services.vm_partition_service import get_vm_partition, get_vm_partitions
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger
from tool_registry import (
    get_tool_by_index,
    get_tool_by_id,
    get_tool_id_from_label,
    get_tool_registry,
    tool_produces_requirement as registry_tool_produces_requirement,
    validate_tool_flag_values,
)
from backend.api.services.job_execution_service import get_executions_by_job

logger = get_logger(__name__)


class KubernetesPipelineRunner:
    """Run CASSIE pipelines as Kubernetes Jobs with DAG-aware scheduling."""

    def __init__(self):
        self._config = get_config()
        self._logger = get_logger(__name__)
        self._resource_cache: Optional[Tuple[float, Dict[str, int]]] = None
        self._checkpoint_events: Dict[int, asyncio.Event] = {}
        self._checkpoint_releases: Dict[int, set[str]] = {}
        self._execution_loops: Dict[int, asyncio.AbstractEventLoop] = {}
        self._stage_executor = ThreadPoolExecutor(
            max_workers=max(1, int(os.getenv("CASSIE_STAGE_EXECUTOR_WORKERS", "8"))),
            thread_name_prefix="cassie-stage",
        )
        self._metadata_executor = ThreadPoolExecutor(
            max_workers=max(1, int(os.getenv("CASSIE_METADATA_EXECUTOR_WORKERS", "4"))),
            thread_name_prefix="cassie-meta",
        )

    async def start_pipeline(
        self,
        job_id: int,
        user_id: int,
        workflow_id: int,
        input_files: List[int],
        execution_number: int = 1,
        execution_id: Optional[int] = None,
        parameters_used: Optional[Dict[str, Any]] = None,
        vm_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """
        Create an execution record and schedule the Kubernetes pipeline.
        """
        namespace = self._config.kubernetes.namespace
        job = get_job_by_id(job_id, user_id=user_id)
        selected_vm_name = vm_name or (job.vm_name if job else None)
        run_id = f"k8s-{job_id}-{execution_number}-{int(datetime.now().timestamp())}"
        work_dir = f"k8s://{namespace}/jobs/{run_id}"
        output_dir = f"{work_dir}/output"

        initial_parameters: Dict[str, Any] = dict(parameters_used or {})
        initial_parameters.update(
            {
                "backend": "kubernetes",
                "namespace": namespace,
                "workflow_id": workflow_id,
                "input_files": list(input_files or []),
                "vm_name": selected_vm_name,
                "queue_state": "running",
                "queue_position": None,
                "stages": list(initial_parameters.get("stages") or []),
            }
        )

        if execution_id is not None:
            update_job_execution(
                execution_id,
                JobExecutionUpdate(
                    status=ExecutionStatus.RUNNING,
                    nextflow_run_id=run_id,
                    work_dir=work_dir,
                    output_dir=output_dir,
                    parameters_used=initial_parameters,
                    started_at=datetime.now(),
                    completed_at=None,
                    error_message=None,
                ),
            )
        else:
            execution_data = JobExecutionCreate(
                job_id=job_id,
                execution_number=execution_number,
                status=ExecutionStatus.RUNNING,
                nextflow_run_id=run_id,
                work_dir=work_dir,
                output_dir=output_dir,
                process_id=None,
                tool_versions={},
                parameters_used=initial_parameters,
                started_at=datetime.now(),
            )
            execution = create_job_execution(execution_data)
            execution_id = execution.id

        from backend.api.models.job_model import JobUpdate

        update_job(job_id, user_id, JobUpdate(status=JobStatus.RUNNING))

        asyncio.create_task(
            self._run_pipeline_async(
                execution_id=execution_id,
                job_id=job_id,
                user_id=user_id,
                workflow_id=workflow_id,
                input_files=input_files,
                parameters_used=initial_parameters,
                vm_name=selected_vm_name,
            )
        )

        return {
            "execution_id": execution_id,
            "status": ExecutionStatus.RUNNING.value,
            "backend": "kubernetes",
            "namespace": namespace,
            "run_id": run_id,
        }

    async def _run_pipeline_async(
        self,
        execution_id: int,
        job_id: int,
        user_id: int,
        workflow_id: int,
        input_files: List[int],
        parameters_used: Dict[str, Any],
        vm_name: Optional[str],
    ) -> None:
        from backend.api.services.vm_queue_service import schedule_queued_jobs
        from backend.api.services.user_notification_service import send_job_checkpoint_notification

        try:
            loop = asyncio.get_event_loop()
            await loop.run_in_executor(self._metadata_executor, self._ensure_cluster_available)

            job = await loop.run_in_executor(
                self._metadata_executor,
                lambda: get_job_by_id(job_id, user_id=user_id),
            )
            workflow = await loop.run_in_executor(
                self._metadata_executor,
                lambda: self._get_workflow(workflow_id, user_id),
            )
            current_inputs = await loop.run_in_executor(
                self._metadata_executor,
                lambda: self._build_initial_inputs(user_id, input_files),
            )
            if not current_inputs:
                raise ValueError("No input files available for Kubernetes execution")

            stage_specs = await loop.run_in_executor(
                self._metadata_executor,
                lambda: self._build_stage_specs(job, workflow, user_id, current_inputs),
            )
            if not stage_specs:
                raise ValueError(f"No valid tools found in workflow {workflow_id}")

            parameters_used["tool_sequence"] = [
                spec["tool"]["id"]
                for spec in stage_specs
                if str(spec.get("stage_kind") or "tool") == "tool"
            ]
            parameters_used["execution_mode"] = "parallel-dag" if getattr(job, "pipeline_id", None) else "sequential"
            parameters_used["stages"] = []
            for spec in stage_specs:
                stage_info = {
                    "stage_id": spec["stage_id"],
                    "stage_number": spec["stage_number"],
                    "tool_id": spec["tool"]["id"],
                    "tool_name": spec["tool"]["name"],
                    "stage_kind": spec.get("stage_kind", "tool"),
                    "dependency_stage_ids": list(spec["dependency_ids"]),
                    "status": "waiting_for_dependencies" if spec["dependency_ids"] else "pending",
                }
                spec["stage_info"] = stage_info
                parameters_used["stages"].append(stage_info)
            await loop.run_in_executor(
                self._metadata_executor,
                lambda: self._persist_execution_state(execution_id, parameters_used),
            )

            tool_versions: Dict[str, str] = {}
            outputs_by_stage: Dict[str, List[Dict[str, Any]]] = {}
            completed_stage_ids: set[str] = set()
            running_stages: Dict[str, Dict[str, Any]] = {}
            job_budget = await loop.run_in_executor(
                self._metadata_executor,
                lambda: self._detect_effective_cluster_capacity(vm_name=vm_name),
            )
            reserved = {"cpu_millis": 0, "memory_mib": 0, "storage_mib": 0}
            checkpoint_event = asyncio.Event()
            released_checkpoints: set[str] = set()
            self._checkpoint_events[execution_id] = checkpoint_event
            self._checkpoint_releases[execution_id] = released_checkpoints
            self._execution_loops[execution_id] = loop

            while len(completed_stage_ids) < len(stage_specs):
                launched_any = False
                ready_without_capacity = False
                waiting_for_checkpoint = False
                state_changed = False

                for spec in stage_specs:
                    stage_id = spec["stage_id"]
                    stage_info = spec["stage_info"]
                    if stage_id in completed_stage_ids or stage_id in running_stages:
                        continue

                    dependencies_met = all(dep_id in completed_stage_ids for dep_id in spec["dependency_ids"])
                    if not dependencies_met:
                        if stage_info.get("status") not in {"completed", "running", "failed"}:
                            stage_info["status"] = "waiting_for_dependencies"
                        continue

                    if str(spec.get("stage_kind") or "tool") == "checkpoint":
                        if stage_id in released_checkpoints:
                            released_checkpoints.discard(stage_id)
                            completed_stage_ids.add(stage_id)
                            outputs_by_stage[stage_id] = self._collect_stage_inputs(spec, current_inputs, outputs_by_stage)
                            stage_info["status"] = "completed"
                            stage_info.setdefault("started_at", datetime.now().isoformat())
                            stage_info["completed_at"] = datetime.now().isoformat()
                            state_changed = True
                            continue

                        waiting_for_checkpoint = True
                        if stage_info.get("status") != "waiting_for_checkpoint":
                            stage_info["status"] = "waiting_for_checkpoint"
                            state_changed = True
                            await loop.run_in_executor(
                                self._metadata_executor,
                                lambda stage_info=stage_info: send_job_checkpoint_notification(
                                    user_id,
                                    job_id=job_id,
                                    job_name=str(getattr(job, "name", f"Job {job_id}") or f"Job {job_id}"),
                                    checkpoint_name=str(stage_info.get("tool_name") or stage_info.get("stage_id") or "Checkpoint"),
                                    stage_number=stage_info.get("stage_number"),
                                ),
                            )
                        continue

                    stage_inputs = self._collect_stage_inputs(spec, current_inputs, outputs_by_stage)
                    tool_plan = self._plan_tool_resources(spec["tool"]["id"], stage_inputs, vm_name=vm_name)
                    spec["current_inputs"] = stage_inputs
                    spec["tool_plan"] = tool_plan

                    fits_budget = self._fits_job_budget(job_budget, reserved, tool_plan)
                    if not fits_budget and not running_stages and not launched_any:
                        tool_plan = self._single_stage_schedulable_plan(job_budget, reserved, tool_plan)
                        spec["tool_plan"] = tool_plan

                    if fits_budget or (not running_stages and not launched_any):
                        stage_job_name = self._make_job_name(job_id, execution_id, spec["stage_number"], spec["tool"]["id"])
                        stage_info["status"] = "running"
                        stage_info["started_at"] = datetime.now().isoformat()
                        stage_info["kubernetes_job_name"] = stage_job_name
                        stage_info["resource_profile"] = tool_plan["profile"]
                        stage_info["threads"] = tool_plan["threads"]
                        stage_info["cpu_limit_millis"] = tool_plan["cpu_limit_millis"]
                        stage_info["memory_limit_mib"] = tool_plan["memory_limit_mib"]
                        stage_info["storage_limit_mib"] = tool_plan["storage_limit_mib"]
                        state_changed = True

                        self._reserve_plan_resources(reserved, tool_plan, direction=1)
                        running_stages[stage_id] = {
                            "spec": spec,
                            "usage": self._plan_usage(tool_plan),
                            "task": loop.run_in_executor(
                                self._stage_executor,
                                lambda spec=spec, stage_job_name=stage_job_name, stage_info=stage_info: self._run_stage(
                                    job_id=job_id,
                                    execution_id=execution_id,
                                    user_id=user_id,
                                    stage_number=spec["stage_number"],
                                    tool=spec["tool"],
                                    stage_job_name=stage_job_name,
                                    current_inputs=spec["current_inputs"],
                                    vm_name=vm_name,
                                    stage_info=stage_info,
                                    parameters_used=parameters_used,
                                    tool_plan=spec["tool_plan"],
                                    tool_config=spec.get("tool_config"),
                                ),
                            ),
                        }
                        tool_versions[spec["tool"]["id"]] = str(spec["tool"].get("docker", {}).get("image", "unknown"))
                        launched_any = True
                    else:
                        ready_without_capacity = True
                        if stage_info.get("status") != "waiting_for_resources":
                            stage_info["status"] = "waiting_for_resources"
                            state_changed = True

                if launched_any or state_changed:
                    await loop.run_in_executor(
                        self._metadata_executor,
                        lambda: self._persist_execution_state(execution_id, parameters_used, tool_versions=tool_versions),
                    )

                if not running_stages:
                    if ready_without_capacity:
                        raise RuntimeError("Pipeline scheduling stalled because no stage could fit inside the selected VM job budget.")
                    if waiting_for_checkpoint:
                        await checkpoint_event.wait()
                        checkpoint_event.clear()
                        continue
                    raise RuntimeError("Pipeline scheduling deadlocked. Check the pipeline dependency graph.")

                done, _ = await asyncio.wait(
                    [entry["task"] for entry in running_stages.values()],
                    return_when=asyncio.FIRST_COMPLETED,
                )

                failed_error: Optional[RuntimeError] = None
                finished_stage_ids: List[str] = []
                for stage_id, entry in list(running_stages.items()):
                    if entry["task"] not in done:
                        continue

                    spec = entry["spec"]
                    stage_info = spec["stage_info"]
                    self._reserve_plan_resources(reserved, spec["tool_plan"], direction=-1)
                    finished_stage_ids.append(stage_id)

                    try:
                        stage_outputs = entry["task"].result()
                    except Exception as exc:
                        public_error = self._public_failure_message(str(exc), tool_name=spec["tool"].get("name"))
                        stage_info["status"] = "failed"
                        stage_info["completed_at"] = datetime.now().isoformat()
                        stage_info["error"] = public_error
                        failed_error = RuntimeError(public_error)
                    else:
                        outputs_by_stage[stage_id] = stage_outputs
                        completed_stage_ids.add(stage_id)
                        stage_info["status"] = "completed"
                        stage_info["completed_at"] = datetime.now().isoformat()
                        stage_info["output_count"] = len(stage_outputs)
                        try:
                            await loop.run_in_executor(
                                self._metadata_executor,
                                lambda spec=spec, stage_id=stage_id, stage_outputs=stage_outputs: append_successful_tool_training_rows(
                                    job_id=job_id,
                                    execution_id=execution_id,
                                    user_id=user_id,
                                    workflow_id=workflow_id,
                                    pipeline_id=getattr(job, "pipeline_id", None),
                                    vm_name=vm_name,
                                    stage_specs=[spec],
                                    outputs_by_stage={stage_id: stage_outputs},
                                ),
                            )
                        except Exception as training_error:
                            self._logger.warning(
                                f"Failed to append tool training data for job {job_id}, execution {execution_id}, stage {stage_id}: {training_error}",
                                exc_info=True,
                            )

                for stage_id in finished_stage_ids:
                    running_stages.pop(stage_id, None)

                await loop.run_in_executor(
                    self._metadata_executor,
                    lambda: self._persist_execution_state(execution_id, parameters_used, tool_versions=tool_versions),
                )

                if failed_error is not None:
                    for entry in running_stages.values():
                        stage_job_name = str(entry["spec"]["stage_info"].get("kubernetes_job_name") or "").strip()
                        if stage_job_name:
                            self._terminate_stage_job(stage_job_name)
                    raise failed_error

            update_job_execution(
                execution_id,
                JobExecutionUpdate(
                    status=ExecutionStatus.COMPLETED,
                    completed_at=datetime.now(),
                    parameters_used=parameters_used,
                    tool_versions=tool_versions,
                ),
            )
            from backend.api.models.job_model import JobUpdate

            update_job(job_id, user_id, JobUpdate(status=JobStatus.COMPLETED))
            settle_job_charge(job_id, user_id, execution_id)
            prewarm_job_outputs_zip(job_id, user_id)
        except Exception as exc:
            public_error = self._public_failure_message(str(exc))
            self._logger.error(
                f"Kubernetes pipeline execution failed for job {job_id}, execution {execution_id}: {exc}",
                exc_info=True,
            )
            update_job_execution(
                execution_id,
                JobExecutionUpdate(
                    status=ExecutionStatus.FAILED,
                    error_message=public_error,
                    completed_at=datetime.now(),
                    parameters_used=parameters_used,
                ),
            )
            from backend.api.models.job_model import JobUpdate

            update_job(job_id, user_id, JobUpdate(status=JobStatus.FAILED))
            settle_job_charge(job_id, user_id, execution_id)
        finally:
            self._checkpoint_events.pop(execution_id, None)
            self._checkpoint_releases.pop(execution_id, None)
            self._execution_loops.pop(execution_id, None)
            try:
                await schedule_queued_jobs(vm_name)
            except Exception as queue_error:
                self._logger.warning(
                    "Failed to schedule queued jobs after execution %s on %s: %s",
                    execution_id,
                    vm_name,
                    queue_error,
                )

    def _public_failure_message(self, raw_error: str, tool_name: Optional[str] = None) -> str:
        """Convert raw Kubernetes/tool output into a short user-facing cause."""
        error_text = raw_error or ""
        normalized = error_text.lower()
        prefix = f"{tool_name} failed: " if tool_name else "Pipeline failed: "
        detail = self._extract_failure_detail(error_text)

        storage_markers = (
            "no space left on device",
            "ephemeral-storage",
            "ephemeral local storage",
            "diskpressure",
            "disk pressure",
            "evicted",
            "emptydir",
            "exceeded its local ephemeral storage limit",
            "insufficient ephemeral-storage",
        )
        if any(marker in normalized for marker in storage_markers):
            return (
                f"{prefix}temporary workspace storage was exhausted. "
                "Increase the Kubernetes/Minikube disk space or raise CASSIE_TOOL_STORAGE_MIB "
                "or the tool-specific *_STORAGE_MIB value, then retry the job."
                f"{detail}"
            )

        memory_markers = (
            "oomkilled",
            "out of memory",
            "cannot allocate memory",
            "memory limit",
            "exit code 137",
            "err code: -9",
            "exit status 137",
            "killed",
        )
        if any(marker in normalized for marker in memory_markers):
            return (
                f"{prefix}memory was exhausted inside the Kubernetes pod. "
                "CASSIE will use the low-resource tool profile when possible, but this dataset may need "
                "more Minikube/Docker memory for the selected tool."
                f"{detail}"
            )

        image_markers = ("imagepullbackoff", "errimagepull", "invalidimagename")
        if any(marker in normalized for marker in image_markers):
            return (
                f"{prefix}the Kubernetes pod could not start because the tool image was not available. "
                "Run the CASSIE start script again so tool images are built and loaded into Minikube."
                f"{detail}"
            )

        cluster_markers = ("cluster is not reachable", "connection refused", "unable to connect to the server")
        if any(marker in normalized for marker in cluster_markers):
            return (
                f"{prefix}the backend could not reach the Kubernetes cluster. "
                "Start CASSIE with the start script so Minikube and the backend kubeconfig are prepared."
                f"{detail}"
            )

        timeout_markers = (
            "exceeded timeout",
            "timed out",
            "timeout expired",
        )
        if any(marker in normalized for marker in timeout_markers):
            if "kubectl command timed out" in normalized:
                return (
                    f"{prefix}the backend took too long waiting for a Kubernetes response while this stage was starting. "
                    "Refresh the job details in a moment and retry only if the stage never begins."
                    f"{detail}"
                )
            return (
                f"{prefix}the Kubernetes stage exceeded the configured execution timeout. "
                "CASSIE is now configured to allow unlimited runtime by default, so retry the job after restarting the backend."
                f"{detail}"
            )

        first_line = self._first_meaningful_line(error_text)
        if first_line:
            return f"{prefix}{first_line}"
        return f"{prefix}an unknown error occurred."

    def _extract_failure_detail(self, raw_error: str) -> str:
        line = self._first_meaningful_line(raw_error)
        if not line:
            return ""
        return f" Detail: {line}"

    def _first_meaningful_line(self, raw_error: str) -> str:
        skip_fragments = (
            "traceback",
            "file \"",
            "runtimeerror:",
            "kubernetes job cassie-",
            "started:",
            "completed:",
            "current progress:",
            "cassie resource profile:",
        )
        for raw_line in raw_error.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            lower = line.lower()
            if any(fragment in lower for fragment in skip_fragments):
                continue
            if len(line) > 240:
                line = f"{line[:237]}..."
            return line
        return ""

    def _ensure_cluster_available(self) -> None:
        timeout = max(5, self._config.kubernetes.cluster_check_timeout_seconds)
        namespace = self._config.kubernetes.namespace
        probes = [
            ["get", "--raw=/readyz?verbose"],
            ["get", "namespace", namespace],
        ]

        last_error = ""
        for probe_args in probes:
            try:
                result = self._run_kubectl(
                    [*probe_args, f"--request-timeout={timeout}s"],
                    timeout=timeout + 5,
                )
            except subprocess.TimeoutExpired:
                last_error = (
                    f"kubectl {' '.join(probe_args)} timed out after {timeout} seconds"
                )
                continue

            if result.returncode == 0:
                return

            stderr = result.stderr.strip()
            stdout = result.stdout.strip()
            last_error = stderr or stdout or f"kubectl {' '.join(probe_args)} failed"

        raise RuntimeError(
            "Kubernetes cluster is not reachable from the backend container. "
            f"Last probe error: {last_error}"
        )

    def _get_workflow(self, workflow_id: int, user_id: int) -> Dict[str, Any]:
        from backend.api.services.workflow_service import get_workflow_by_id

        workflow = get_workflow_by_id(workflow_id, user_id=user_id)
        if not workflow:
            raise ValueError(f"Workflow {workflow_id} not found")
        return workflow

    def _resolve_workflow_tools(self, workflow: Dict[str, Any]) -> List[Dict[str, Any]]:
        resolved: List[Dict[str, Any]] = []
        seen_ids = set()

        for step in workflow.get("workflow_steps", []) or []:
            tool_id = step.get("tool")
            tool = get_tool_by_id(tool_id) if tool_id else None
            if tool and tool["id"] not in seen_ids:
                resolved.append(tool)
                seen_ids.add(tool["id"])

        if resolved:
            return resolved

        for item in workflow.get("tools_used", []) or []:
            tool = get_tool_by_id(str(item).upper())
            if not tool:
                for candidate in get_tool_registry():
                    if candidate["name"].lower() == str(item).strip().lower():
                        tool = candidate
                        break
            if tool and tool["id"] not in seen_ids:
                resolved.append(tool)
                seen_ids.add(tool["id"])

        return resolved

    def _build_stage_specs(
        self,
        job: Optional[Any],
        workflow: Dict[str, Any],
        user_id: int,
        initial_inputs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        execution_preferences = getattr(job, "execution_preferences", None) if job else None
        if getattr(job, "pipeline_id", None):
            pipeline_specs = self._build_stage_specs_from_pipeline(
                job.pipeline_id,
                user_id,
                execution_preferences=execution_preferences,
            )
            if pipeline_specs:
                return pipeline_specs

        workflow_specs = self._build_stage_specs_from_workflow(
            workflow,
            execution_preferences=execution_preferences,
        )
        if workflow_specs and any(spec.get("dependency_ids") for spec in workflow_specs):
            return workflow_specs

        tools = self._resolve_workflow_tools(workflow)
        if workflow_specs:
            tools = [spec["tool"] for spec in workflow_specs]
        return self._infer_stage_specs_from_tools(tools, initial_inputs, execution_preferences=execution_preferences)

    def _build_stage_specs_from_workflow(
        self,
        workflow: Dict[str, Any],
        execution_preferences: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        manual_override_positions: Dict[str, int] = {}

        if isinstance(execution_preferences, dict):
            for group in execution_preferences.get("manual_priority_groups") or []:
                if not isinstance(group, dict):
                    continue
                ordered_tool_ids = group.get("ordered_tool_ids") or []
                if not isinstance(ordered_tool_ids, list):
                    continue
                for index, tool_id in enumerate(ordered_tool_ids):
                    normalized_tool_id = str(tool_id).strip().upper()
                    if normalized_tool_id and normalized_tool_id not in manual_override_positions:
                        manual_override_positions[normalized_tool_id] = index

        for stage_number, step in enumerate(workflow.get("workflow_steps", []) or [], start=1):
            tool_id = str(step.get("tool") or "").strip().upper()
            tool = get_tool_by_id(tool_id) if tool_id else None
            if not tool:
                continue

            stage_id = str(step.get("stage_id") or step.get("id") or f"step-{stage_number}")
            dependency_ids = [str(dep).strip() for dep in (step.get("dependency_ids") or []) if str(dep).strip()]
            specs.append(
                {
                    "stage_id": stage_id,
                    "stage_number": stage_number,
                    "tool": tool,
                    "dependency_ids": dependency_ids,
                    "priority_order": manual_override_positions.get(tool_id, stage_number - 1),
                }
            )

        self._populate_inferred_stage_dependencies(specs, execution_preferences)
        return self._topologically_order_stage_specs(specs)

    def _infer_stage_specs_from_tools(
        self,
        tools: List[Dict[str, Any]],
        initial_inputs: List[Dict[str, Any]],
        execution_preferences: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        manual_override_positions: Dict[str, int] = {}

        if isinstance(execution_preferences, dict):
            for group in execution_preferences.get("manual_priority_groups") or []:
                if not isinstance(group, dict):
                    continue
                ordered_tool_ids = group.get("ordered_tool_ids") or []
                if not isinstance(ordered_tool_ids, list):
                    continue
                for index, tool_id in enumerate(ordered_tool_ids):
                    normalized_tool_id = str(tool_id).strip().upper()
                    if normalized_tool_id and normalized_tool_id not in manual_override_positions:
                        manual_override_positions[normalized_tool_id] = index

        for stage_number, tool in enumerate(tools, start=1):
            stage_id = f"step-{stage_number}"
            specs.append(
                {
                    "stage_id": stage_id,
                    "stage_number": stage_number,
                    "tool": tool,
                    "dependency_ids": [],
                    "priority_order": manual_override_positions.get(str(tool.get("id") or "").strip().upper(), stage_number - 1),
                }
            )

        self._populate_inferred_stage_dependencies(specs, execution_preferences)
        return self._topologically_order_stage_specs(specs)

    def _populate_inferred_stage_dependencies(
        self,
        specs: List[Dict[str, Any]],
        execution_preferences: Optional[Dict[str, Any]],
    ) -> None:
        """Attach upstream producer stages to requirements marked as upstream."""
        for spec in specs:
            tool = spec.get("tool") or {}
            current_stage_id = str(spec.get("stage_id") or "")
            dependency_ids: List[str] = [
                str(dependency_id).strip()
                for dependency_id in (spec.get("dependency_ids") or [])
                if str(dependency_id).strip()
            ]

            for requirement in tool.get("input_requirements", []) or []:
                requirement_type = str(requirement.get("type") or "").strip().lower()
                if not requirement_type:
                    continue
                if self._get_requirement_source_override(execution_preferences, str(tool.get("id") or ""), requirement_type) == "external":
                    continue
                for producer_spec in specs:
                    producer_stage_id = str(producer_spec.get("stage_id") or "")
                    if not producer_stage_id or producer_stage_id == current_stage_id:
                        continue
                    if self._tool_produces_requirement(producer_spec.get("tool", {}), requirement_type):
                        dependency_ids.append(producer_stage_id)

            deduped_dependencies: List[str] = []
            seen_dependency_ids: set[str] = set()
            for dependency_id in dependency_ids:
                if dependency_id in seen_dependency_ids:
                    continue
                deduped_dependencies.append(dependency_id)
                seen_dependency_ids.add(dependency_id)
            spec["dependency_ids"] = deduped_dependencies

    def _topologically_order_stage_specs(self, specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        spec_by_id = {str(spec.get("stage_id") or ""): spec for spec in specs}
        dependents: Dict[str, List[str]] = {stage_id: [] for stage_id in spec_by_id}
        in_degree: Dict[str, int] = {stage_id: 0 for stage_id in spec_by_id}

        for spec in specs:
            stage_id = str(spec.get("stage_id") or "")
            valid_dependencies = [
                dependency_id
                for dependency_id in (spec.get("dependency_ids") or [])
                if dependency_id in spec_by_id and dependency_id != stage_id
            ]
            spec["dependency_ids"] = valid_dependencies
            in_degree[stage_id] = len(valid_dependencies)
            for dependency_id in valid_dependencies:
                dependents.setdefault(dependency_id, []).append(stage_id)

        def sort_key(stage_id: str) -> Tuple[int, int, str]:
            spec = spec_by_id.get(stage_id) or {}
            return (
                int(spec.get("priority_order") or 0),
                int(spec.get("stage_number") or 0),
                stage_id,
            )

        ready = sorted([stage_id for stage_id, degree in in_degree.items() if degree == 0], key=sort_key)
        ordered_ids: List[str] = []
        while ready:
            stage_id = ready.pop(0)
            ordered_ids.append(stage_id)
            for dependent_id in sorted(dependents.get(stage_id) or [], key=sort_key):
                in_degree[dependent_id] = max(0, in_degree.get(dependent_id, 0) - 1)
                if in_degree[dependent_id] == 0 and dependent_id not in ready and dependent_id not in ordered_ids:
                    ready.append(dependent_id)
                    ready.sort(key=sort_key)

        for spec in sorted(specs, key=lambda item: sort_key(str(item.get("stage_id") or ""))):
            stage_id = str(spec.get("stage_id") or "")
            if stage_id not in ordered_ids:
                ordered_ids.append(stage_id)

        ordered_specs = [spec_by_id[stage_id] for stage_id in ordered_ids if stage_id in spec_by_id]
        for stage_number, spec in enumerate(ordered_specs, start=1):
            spec["stage_number"] = stage_number
            spec.pop("priority_order", None)
        return ordered_specs

    def _tool_produces_requirement(self, tool: Dict[str, Any], requirement_type: str) -> bool:
        return registry_tool_produces_requirement(tool, requirement_type)

    def _get_requirement_source_override(
        self,
        execution_preferences: Optional[Dict[str, Any]],
        tool_id: str,
        requirement_type: str,
    ) -> Optional[str]:
        normalized_tool_id = str(tool_id or "").strip().upper()
        normalized_requirement = str(requirement_type or "").strip().lower()
        if not normalized_tool_id or not normalized_requirement or not isinstance(execution_preferences, dict):
            return None

        for item in execution_preferences.get("input_source_overrides") or []:
            if not isinstance(item, dict):
                continue
            item_tool_id = str(item.get("tool_id") or "").strip().upper()
            item_requirement = str(item.get("requirement_type") or "").strip().lower()
            source = str(item.get("source") or "").strip().lower()
            if item_tool_id == normalized_tool_id and item_requirement == normalized_requirement and source in {"external", "upstream"}:
                return source
        return None

    def _build_stage_specs_from_pipeline(
        self,
        pipeline_id: int,
        user_id: int,
        execution_preferences: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        from backend.api.services.pipeline_converter import (
            build_stage_result_label_map,
            extract_edges,
            extract_stage_nodes,
            resolve_node_label,
            resolve_node_tool_id,
            sort_tool_nodes_by_priority,
        )
        from backend.api.services.pipeline_service import get_pipeline_by_id

        pipeline = get_pipeline_by_id(pipeline_id, user_id)
        if not pipeline:
            return []

        stage_nodes = extract_stage_nodes(pipeline.nodes)
        if not stage_nodes:
            return []

        edges = extract_edges(pipeline.edges)
        result_labels_by_stage = build_stage_result_label_map(pipeline.nodes, pipeline.edges)
        dependency_map: Dict[str, List[str]] = {node_id: [] for node_id in stage_nodes}
        for edge in edges:
            source = str(edge.get("source") or "").strip()
            target = str(edge.get("target") or "").strip()
            if source in stage_nodes and target in stage_nodes and source not in dependency_map[target]:
                dependency_map[target].append(source)

        priority_overrides = []
        if isinstance(execution_preferences, dict):
            priority_overrides = execution_preferences.get("pipeline_priority_groups") or []

        ordered_node_ids = sort_tool_nodes_by_priority(
            stage_nodes,
            edges,
            priority_overrides=priority_overrides,
        )
        specs: List[Dict[str, Any]] = []
        stage_number = 1
        for node_id in ordered_node_ids:
            node = stage_nodes.get(node_id)
            if not node:
                continue
            node_type = str(node.get("type") or "").strip().lower()
            if node_type == "checkpoint":
                tool = {
                    "id": "CHECKPOINT",
                    "name": resolve_node_label(node) or "Checkpoint",
                    "docker": {},
                    "input_requirements": [],
                }
                tool_config = {}
                stage_kind = "checkpoint"
            else:
                tool_id = resolve_node_tool_id(node)
                tool = get_tool_by_id(tool_id) if tool_id else None
                if not tool:
                    continue
                tool_config = self._extract_pipeline_node_config(node)
                stage_kind = "tool"
            stage_label = resolve_node_label(node) or str((tool or {}).get("name") or (tool or {}).get("id") or node_id)
            specs.append(
                {
                    "stage_id": node_id,
                    "stage_number": stage_number,
                    "tool": tool,
                    "dependency_ids": list(dependency_map.get(node_id, [])),
                    "tool_config": tool_config,
                    "stage_kind": stage_kind,
                    "priority_order": int(((node.get("data") or {}).get("priorityOrder")) or stage_number - 1),
                    "stage_label": stage_label,
                    "result_labels": list(result_labels_by_stage.get(node_id, [])),
                }
            )
            stage_number += 1

        return specs

    def _collect_stage_inputs(
        self,
        spec: Dict[str, Any],
        initial_inputs: List[Dict[str, Any]],
        outputs_by_stage: Dict[str, List[Dict[str, Any]]],
    ) -> List[Dict[str, Any]]:
        artifacts: List[Dict[str, Any]] = [dict(item) for item in initial_inputs]
        seen_keys = {
            (str(item.get("s3_key") or ""), str(item.get("filename") or ""))
            for item in artifacts
        }

        for dependency_id in spec.get("dependency_ids", []):
            for artifact in outputs_by_stage.get(dependency_id, []) or []:
                dedupe_key = (str(artifact.get("s3_key") or ""), str(artifact.get("filename") or ""))
                if dedupe_key in seen_keys:
                    continue
                artifacts.append(dict(artifact))
                seen_keys.add(dedupe_key)

        return artifacts

    def _extract_pipeline_node_config(self, node: Dict[str, Any]) -> Dict[str, Any]:
        node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
        raw_values = node_data.get("flagValues") or node_data.get("toolConfig") or {}
        if not isinstance(raw_values, dict):
            return {}

        explicit_tool_id = str(node_data.get("toolId") or node_data.get("tool_id") or "").strip().upper()
        label = str(node_data.get("label") or node.get("label") or "").strip()
        tool_id = explicit_tool_id or get_tool_id_from_label(label)
        if not tool_id:
            return {}

        validation = validate_tool_flag_values(tool_id, raw_values)
        if validation["errors"]:
            raise ValueError(
                f'Pipeline tool "{label or tool_id}" has invalid configuration: '
                + "; ".join(f"{key}: {value}" for key, value in validation["errors"].items())
            )
        return validation["values"]

    def _classify_pipeline_input_node(self, node: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        node_type = str(node.get("type") or node.get("nodeType") or "").strip().lower()
        if node_type not in {"fastqinput", "fastainput", "input", "inputnode", "start"}:
            return None

        node_data = node.get("data") if isinstance(node.get("data"), dict) else {}
        label = str(node_data.get("label") or node.get("label") or "").strip()
        description = node_data.get("description") if isinstance(node_data, dict) else None
        description_text = " ".join(description or []).lower() if isinstance(description, list) else str(description or "").lower()
        label_lower = label.lower()

        if node_type == "fastqinput" or "fastq" in label_lower or "fastq" in description_text:
            return {"type": "fastq_input", "label": label or "FASTQ Input", "formats": ["fastq"]}
        if node_type == "fastainput" or "fasta" in label_lower or "fasta" in description_text or "reference" in label_lower:
            return {"type": "fasta_input", "label": label or "FASTA Input", "formats": ["fasta"]}
        if "gff" in label_lower or "gtf" in label_lower or "annotation" in label_lower:
            return {"type": "annotation_input", "label": label or "Annotation Input", "formats": ["gff", "gff3", "gtf"]}
        if "hal" in label_lower:
            return {"type": "hal_input", "label": label or "HAL Input", "formats": ["hal"]}
        if "meryl" in label_lower:
            return {"type": "meryl_input", "label": label or "Meryl Input", "formats": ["meryl"]}
        if "text" in label_lower or "txt" in label_lower or "name" in label_lower or "config" in label_lower:
            return {"type": "text_input", "label": label or "Text Input", "formats": ["txt"]}
        return {"type": "input", "label": label or "Pipeline Input", "formats": []}

    def _select_preview_inputs(
        self,
        initial_inputs: List[Dict[str, Any]],
        *,
        binding_ids: Optional[List[str]] = None,
        tool_id: Optional[str] = None,
        requirement_type: Optional[str] = None,
        requirement: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        normalized_binding_ids = {
            str(binding_id).strip()
            for binding_id in (binding_ids or [])
            if str(binding_id).strip()
        }
        normalized_tool_id = str(tool_id or "").strip().upper()
        normalized_requirement_type = str(requirement_type or "").strip().lower()

        targeted_matches: List[Dict[str, Any]] = []
        for artifact in initial_inputs:
            artifact_binding_id = str(artifact.get("binding_id") or "").strip()
            artifact_tool_id = str(artifact.get("tool_id") or "").strip().upper()
            artifact_requirement_type = str(artifact.get("requirement_type") or "").strip().lower()

            if normalized_binding_ids and artifact_binding_id in normalized_binding_ids:
                targeted_matches.append(artifact)
                continue

            if (
                normalized_tool_id
                and normalized_requirement_type
                and artifact_tool_id == normalized_tool_id
                and artifact_requirement_type == normalized_requirement_type
            ):
                targeted_matches.append(artifact)

        if targeted_matches:
            return targeted_matches

        if requirement is None:
            return list(initial_inputs)

        return [
            artifact for artifact in initial_inputs
            if self._artifact_matches_requirement(artifact, requirement)
        ]

    def _resolve_preview_input_label(
        self,
        default_label: str,
        matching_inputs: List[Dict[str, Any]],
    ) -> str:
        for artifact in matching_inputs:
            label = str(artifact.get("label") or "").strip()
            if label:
                return label
        return default_label

    def _build_explicit_pipeline_input_blocks(
        self,
        pipeline_id: int,
        user_id: int,
        stage_specs: List[Dict[str, Any]],
        initial_inputs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        from backend.api.services.pipeline_converter import extract_edges
        from backend.api.services.pipeline_service import get_pipeline_by_id

        pipeline = get_pipeline_by_id(pipeline_id, user_id)
        if not pipeline:
            return [], []

        raw_nodes = pipeline.nodes
        if isinstance(raw_nodes, dict):
            node_list = raw_nodes.get("nodes") if isinstance(raw_nodes.get("nodes"), list) else list(raw_nodes.values())
        elif isinstance(raw_nodes, list):
            node_list = raw_nodes
        else:
            node_list = []

        nodes_by_id = {
            str(node.get("id")): node
            for node in node_list
            if isinstance(node, dict) and node.get("id") is not None
        }
        edges = extract_edges(pipeline.edges)
        stage_numbers = {str(spec.get("stage_id") or ""): int(spec.get("stage_number") or 0) for spec in stage_specs}
        stage_spec_by_id = {str(spec.get("stage_id") or ""): spec for spec in stage_specs}
        blocks: List[Dict[str, Any]] = []
        connections: List[Dict[str, Any]] = []

        for node_id, node in nodes_by_id.items():
            classification = self._classify_pipeline_input_node(node)
            if not classification:
                continue

            downstream_stage_ids = []
            for edge in edges:
                source = str(edge.get("source") or "").strip()
                target = str(edge.get("target") or "").strip()
                if source == node_id and target in stage_numbers and target not in downstream_stage_ids:
                    downstream_stage_ids.append(target)

            requirement = {"formats": classification.get("formats") or []}
            matching_inputs = self._select_preview_inputs(
                initial_inputs,
                binding_ids=[node_id, f"input:{node_id}"],
                requirement=requirement if classification.get("formats") else None,
            )
            block_label = self._resolve_preview_input_label(
                str(classification.get("label") or "Pipeline Input"),
                matching_inputs,
            )

            block_id = f"input:{node_id}"
            blocks.append(
                {
                    "id": block_id,
                    "kind": "input",
                    "column": "input",
                    "row": min((stage_numbers.get(stage_id) or 1) for stage_id in downstream_stage_ids) if downstream_stage_ids else 1,
                    "label": block_label,
                    "status": "finished" if matching_inputs else "waiting",
                    "raw_status": "available" if matching_inputs else "missing",
                    "formats": list(classification.get("formats") or []),
                    "filenames": [str(item.get("filename") or "") for item in matching_inputs if str(item.get("filename") or "").strip()],
                    "description": (
                        ", ".join(str(item.get("filename") or "") for item in matching_inputs if str(item.get("filename") or "").strip())
                        if matching_inputs else
                        "Waiting for a matching job input"
                    ),
                }
            )

            for stage_id in downstream_stage_ids:
                spec = stage_spec_by_id.get(stage_id) or {}
                tool = spec.get("tool") or {}
                label_parts = []
                for requirement in tool.get("input_requirements", []) or []:
                    requirement_label = str(requirement.get("label") or self._humanize_token(str(requirement.get("type") or "input"))).strip()
                    if requirement_label and requirement_label not in label_parts:
                        label_parts.append(requirement_label)
                connections.append(
                    {
                        "id": f"edge:{block_id}:stage:{stage_id}",
                        "source": block_id,
                        "target": f"stage:{stage_id}",
                        "kind": "input",
                        "label": ", ".join(label_parts[:2]) if label_parts else None,
                    }
                )

        return blocks, connections

    def _build_requirement_input_blocks(
        self,
        stage_specs: List[Dict[str, Any]],
        initial_inputs: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        stage_spec_by_id = {str(spec.get("stage_id") or ""): spec for spec in stage_specs}
        blocks: List[Dict[str, Any]] = []
        connections: List[Dict[str, Any]] = []

        for spec in stage_specs:
            if str(spec.get("stage_kind") or "tool") != "tool":
                continue

            stage_id = str(spec.get("stage_id") or "")
            tool = spec.get("tool") or {}
            normalized_tool_id = str(tool.get("id") or "").strip().upper()
            dependency_ids = list(spec.get("dependency_ids") or [])
            for requirement_index, requirement in enumerate(tool.get("input_requirements", []) or []):
                requirement_type = str(requirement.get("type") or "").strip().lower()
                if not requirement_type:
                    continue

                satisfied_by_dependency = any(
                    self._tool_produces_requirement((stage_spec_by_id.get(dependency_id) or {}).get("tool", {}), requirement_type)
                    for dependency_id in dependency_ids
                )
                if satisfied_by_dependency:
                    continue

                binding_id = f"{stage_id}:{normalized_tool_id or 'tool'}:{requirement_type}:{requirement_index}"
                matching_inputs = self._select_preview_inputs(
                    initial_inputs,
                    binding_ids=[binding_id],
                    tool_id=normalized_tool_id or None,
                    requirement_type=requirement_type,
                    requirement=requirement,
                )
                block_label = self._resolve_preview_input_label(
                    str(requirement.get("label") or self._humanize_token(requirement_type)),
                    matching_inputs,
                )
                input_block_id = f"input:{stage_id}:{requirement_type}:{requirement_index}"

                blocks.append(
                    {
                        "id": input_block_id,
                        "kind": "input",
                        "column": "input",
                        "row": int(spec.get("stage_number") or 1),
                        "label": block_label,
                        "status": "finished" if matching_inputs else "waiting",
                        "raw_status": "available" if matching_inputs else "missing",
                        "formats": list(requirement.get("formats") or []),
                        "filenames": [str(item.get("filename") or "") for item in matching_inputs if str(item.get("filename") or "").strip()],
                        "description": (
                            ", ".join(str(item.get("filename") or "") for item in matching_inputs if str(item.get("filename") or "").strip())
                            if matching_inputs else
                            "Waiting for a matching job input"
                        ),
                    }
                )
                connections.append(
                    {
                        "id": f"edge:{input_block_id}:stage:{stage_id}",
                        "source": input_block_id,
                        "target": f"stage:{stage_id}",
                        "kind": "input",
                        "label": block_label,
                    }
                )

        return blocks, connections

    def _build_stage_connections(self, stage_specs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        spec_by_id = {str(spec.get("stage_id") or ""): spec for spec in stage_specs}
        connections: List[Dict[str, Any]] = []

        for spec in stage_specs:
            stage_id = str(spec.get("stage_id") or "")
            if not stage_id:
                continue

            requirement_labels: Dict[str, str] = {}
            for requirement in (spec.get("tool") or {}).get("input_requirements", []) or []:
                requirement_type = str(requirement.get("type") or "").strip().lower()
                if requirement_type:
                    requirement_labels[requirement_type] = str(
                        requirement.get("label") or self._humanize_token(requirement_type)
                    )

            for dependency_id in spec.get("dependency_ids", []) or []:
                dependency_spec = spec_by_id.get(str(dependency_id))
                if not dependency_spec:
                    continue

                produced_labels = []
                for requirement_type, requirement_label in requirement_labels.items():
                    if self._tool_produces_requirement(dependency_spec.get("tool", {}), requirement_type):
                        if requirement_label not in produced_labels:
                            produced_labels.append(requirement_label)

                connections.append(
                    {
                        "id": f"edge:stage:{dependency_id}:stage:{stage_id}",
                        "source": f"stage:{dependency_id}",
                        "target": f"stage:{stage_id}",
                        "kind": "dependency",
                        "label": ", ".join(produced_labels[:2]) if produced_labels else None,
                    }
                )

        return connections

    def _build_output_blocks(
        self,
        stage_specs: List[Dict[str, Any]],
        stage_status_map: Dict[str, Dict[str, Any]],
        output_files: List[Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        def sanitize_output_token(value: str, fallback: str) -> str:
            cleaned = "".join(char.lower() if char.isalnum() else "_" for char in str(value or "").strip())
            collapsed = "_".join(part for part in cleaned.split("_") if part)
            return collapsed or fallback

        def format_output_label(result_label: str, tool_payload: Dict[str, Any], produced_type: str) -> str:
            result_token = sanitize_output_token(result_label, "result")
            tool_token = sanitize_output_token(
                str(tool_payload.get("id") or tool_payload.get("name") or "tool"),
                "tool",
            )
            format_token = sanitize_output_token(produced_type, "output")
            return f"{result_token}_{tool_token}.{format_token}"

        dependents_by_stage: Dict[str, List[Dict[str, Any]]] = {}
        for spec in stage_specs:
            for dependency_id in spec.get("dependency_ids", []) or []:
                dependents_by_stage.setdefault(str(dependency_id), []).append(spec)

        blocks: List[Dict[str, Any]] = []
        connections: List[Dict[str, Any]] = []
        spec_by_id = {str(spec.get("stage_id") or ""): spec for spec in stage_specs}

        for spec in stage_specs:
            if str(spec.get("stage_kind") or "tool") != "tool":
                continue

            stage_id = str(spec.get("stage_id") or "")
            raw_stage_status = str((stage_status_map.get(stage_id) or {}).get("status") or "pending")
            tool = spec.get("tool") or {}
            result_labels = list(spec.get("result_labels") or [])
            downstream_specs = dependents_by_stage.get(stage_id) or []

            for produced_type in list(tool.get("produces") or []):
                produced_tool = {"produces": [produced_type]}
                consumer_stage_ids = [
                    str(downstream_spec.get("stage_id") or "")
                    for downstream_spec in downstream_specs
                    if any(
                        self._tool_produces_requirement(produced_tool, str(requirement.get("type") or "").strip().lower())
                        for requirement in ((downstream_spec.get("tool") or {}).get("input_requirements") or [])
                    )
                ]

                output_block_id = f"output:{stage_id}:{produced_type}"
                stage_entry = stage_status_map.get(stage_id)
                matching_outputs = [
                    file_record for file_record in output_files
                    if self._output_matches_stage(file_record, tool, produced_type)
                ]
                blocks.append(
                    {
                        "id": output_block_id,
                        "kind": "output",
                        "column": "output",
                        "row": int(spec.get("stage_number") or 0),
                        "label": format_output_label(result_labels[0] if result_labels else "result", tool, str(produced_type or "output")),
                        "status": self._derive_output_status(raw_stage_status, matching_outputs),
                        "raw_status": raw_stage_status,
                        "related_stage_id": stage_id,
                        "produced_type": str(produced_type),
                        "consumer_stage_ids": consumer_stage_ids,
                        "filenames": [file_record.filename for file_record in matching_outputs],
                        "description": (
                            ", ".join(file_record.filename for file_record in matching_outputs[:3])
                            + (" ..." if len(matching_outputs) > 3 else "")
                        ) if matching_outputs else (
                            f"{int(stage_entry.get('output_count') or 0)} output file{'s' if int(stage_entry.get('output_count') or 0) != 1 else ''} recorded"
                            if isinstance(stage_entry, dict) and stage_entry.get("output_count") is not None else
                            (
                                f"Produced by {tool.get('name') or tool.get('id')}"
                                + (f" for result block {result_labels[0]}" if result_labels else "")
                            )
                        )
                    }
                )
                connections.append(
                    {
                        "id": f"edge:stage:{stage_id}:{output_block_id}",
                        "source": f"stage:{stage_id}",
                        "target": output_block_id,
                        "kind": "output",
                        "label": self._humanize_token(str(produced_type or "output")),
                    }
                )
                for consumer_stage_id in consumer_stage_ids:
                    if consumer_stage_id not in spec_by_id:
                        continue
                    consumer_spec = spec_by_id.get(consumer_stage_id) or {}
                    matching_requirement_labels = []
                    for requirement in ((consumer_spec.get("tool") or {}).get("input_requirements") or []):
                        requirement_type = str(requirement.get("type") or "").strip().lower()
                        if requirement_type and self._tool_produces_requirement(produced_tool, requirement_type):
                            requirement_label = str(requirement.get("label") or self._humanize_token(requirement_type))
                            if requirement_label not in matching_requirement_labels:
                                matching_requirement_labels.append(requirement_label)
                    connections.append(
                        {
                            "id": f"edge:{output_block_id}:stage:{consumer_stage_id}",
                            "source": output_block_id,
                            "target": f"stage:{consumer_stage_id}",
                            "kind": "artifact",
                            "label": ", ".join(matching_requirement_labels[:2]) if matching_requirement_labels else self._humanize_token(str(produced_type or "output")),
                        }
                    )

        return blocks, connections

    def build_pipeline_plan_preview(
        self,
        *,
        user_id: int,
        tool_indices: Optional[List[int]] = None,
        pipeline_id: Optional[int] = None,
        input_file_ids: Optional[List[int]] = None,
        planned_inputs: Optional[List[Dict[str, Any]]] = None,
        execution_preferences: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Build the same visualization shape as a job without creating or running a job."""
        normalized_inputs: List[Dict[str, Any]] = []
        if planned_inputs:
            for item in planned_inputs:
                if not isinstance(item, dict):
                    continue
                filename = str(item.get("filename") or "").strip()
                if not filename:
                    continue
                normalized_inputs.append(
                    {
                        "filename": filename,
                        "s3_key": str(item.get("s3_key") or ""),
                        "size_bytes": int(item.get("size_bytes") or 0),
                        "binding_id": str(item.get("binding_id") or ""),
                        "tool_id": str(item.get("tool_id") or ""),
                        "requirement_type": str(item.get("requirement_type") or ""),
                        "label": str(item.get("label") or ""),
                        "file_format": item.get("file_format"),
                        "source": str(item.get("source") or "planned-input"),
                        "producer_tool_id": None,
                    }
                )
        elif input_file_ids:
            normalized_inputs = self._build_initial_inputs(user_id, input_file_ids)

        if pipeline_id:
            stage_specs = self._build_stage_specs_from_pipeline(
                pipeline_id,
                user_id,
                execution_preferences=execution_preferences,
            )
            if not stage_specs:
                raise ValueError(f"Pipeline {pipeline_id} could not be converted into an execution plan")
            input_blocks, input_connections = self._build_explicit_pipeline_input_blocks(
                pipeline_id,
                user_id,
                stage_specs,
                normalized_inputs,
            )
        else:
            if not tool_indices:
                raise ValueError("At least one tool index is required to preview a manual pipeline plan")

            tools: List[Dict[str, Any]] = []
            for index in tool_indices:
                tool = get_tool_by_index(index)
                if not tool:
                    raise ValueError(f"Invalid tool index: {index}")
                tools.append(tool)

            stage_specs = self._infer_stage_specs_from_tools(
                tools,
                normalized_inputs,
                execution_preferences=execution_preferences,
            )
            input_blocks, input_connections = self._build_requirement_input_blocks(
                stage_specs,
                normalized_inputs,
            )

        stage_status_map: Dict[str, Dict[str, Any]] = {}
        stage_blocks: List[Dict[str, Any]] = []
        for spec in stage_specs:
            stage_id = str(spec["stage_id"])
            tool = spec["tool"]
            stage_blocks.append(
                {
                    "id": f"stage:{stage_id}",
                    "kind": str(spec.get("stage_kind") or "tool"),
                    "column": "stage",
                    "row": int(spec.get("stage_number") or 0),
                    "stage_id": stage_id,
                    "stage_number": int(spec.get("stage_number") or 0),
                    "label": str(spec.get("stage_label") or tool.get("name") or tool.get("id") or stage_id),
                    "tool_id": str(tool.get("id") or "") or None,
                    "status": "waiting",
                    "raw_status": "planned",
                    "dependency_stage_ids": list(spec.get("dependency_ids") or []),
                    "description": self._build_stage_description(spec, None),
                }
            )

        stage_connections = self._build_stage_connections(stage_specs)
        output_blocks, output_connections = self._build_output_blocks(stage_specs, stage_status_map, [])

        blocks: List[Dict[str, Any]] = []
        blocks.extend(input_blocks)
        blocks.extend(stage_blocks)
        blocks.extend(output_blocks)
        blocks.sort(
            key=lambda block: (
                int(block.get("row") or 0),
                {"input": 0, "stage": 1, "output": 2}.get(str(block.get("column") or ""), 3),
                str(block.get("label") or ""),
            )
        )

        return {
            "job_id": 0,
            "workflow_id": 0,
            "latest_execution_id": None,
            "blocks": blocks,
            "connections": input_connections + stage_connections + output_connections,
        }

    def _plan_usage(self, tool_plan: Dict[str, Any]) -> Dict[str, int]:
        return {
            "cpu_millis": int(tool_plan.get("cpu_limit_millis") or 0),
            "memory_mib": int(tool_plan.get("memory_limit_mib") or 0),
            "storage_mib": int(tool_plan.get("storage_limit_mib") or 0),
        }

    def get_job_pipeline_visualization(self, job_id: int, user_id: int) -> Dict[str, Any]:
        """Build a job-scoped pipeline view from the resolved executable graph."""
        job = get_job_by_id(job_id, user_id=user_id)
        if not job:
            raise ValueError(f"Job {job_id} not found")

        input_files = get_files_by_user(user_id, job_id=job_id, file_type=FileType.INPUT, limit=1000, offset=0)
        output_files = get_files_by_user(user_id, job_id=job_id, file_type=FileType.OUTPUT, limit=1000, offset=0)
        initial_inputs = self._build_initial_inputs(user_id, [file_record.id for file_record in input_files]) if input_files else []

        snapshot_stages = None
        if isinstance(getattr(job, "execution_preferences", None), dict):
            snapshot = job.execution_preferences.get("visualization_snapshot") or {}
            if isinstance(snapshot, dict) and isinstance(snapshot.get("stages"), list):
                snapshot_stages = snapshot.get("stages")

        stage_specs = self._build_visualization_specs_from_snapshot(snapshot_stages)
        if not stage_specs:
            workflow = self._get_workflow(job.workflow_id, user_id)
            stage_specs = self._build_stage_specs(job, workflow, user_id, initial_inputs)

        executions = get_executions_by_job(job_id)
        latest_execution = executions[0] if executions else None
        latest_stage_entries = (
            latest_execution.parameters_used.get("stages")
            if latest_execution and isinstance(latest_execution.parameters_used, dict)
            else []
        )
        if not isinstance(latest_stage_entries, list):
            latest_stage_entries = []

        stage_status_map = {
            str(stage.get("stage_id") or "").strip(): stage
            for stage in latest_stage_entries
            if isinstance(stage, dict) and str(stage.get("stage_id") or "").strip()
        }
        stage_blocks: List[Dict[str, Any]] = []

        for spec in stage_specs:
            stage_id = str(spec["stage_id"])
            tool = spec["tool"]
            raw_stage_status = str((stage_status_map.get(stage_id) or {}).get("status") or "pending")
            stage_blocks.append(
                {
                    "id": f"stage:{stage_id}",
                    "kind": str(spec.get("stage_kind") or "tool"),
                    "column": "stage",
                    "row": int(spec.get("stage_number") or 0),
                    "stage_id": stage_id,
                    "stage_number": int(spec.get("stage_number") or 0),
                    "label": str(spec.get("stage_label") or tool.get("name") or tool.get("id") or stage_id),
                    "tool_id": str(tool.get("id") or "") or None,
                    "status": self._normalize_visual_status(raw_stage_status),
                    "raw_status": raw_stage_status,
                    "dependency_stage_ids": list(spec.get("dependency_ids") or []),
                    "description": self._build_stage_description(spec, stage_status_map.get(stage_id)),
                }
            )

        if getattr(job, "pipeline_id", None):
            input_blocks, input_connections = self._build_explicit_pipeline_input_blocks(
                job.pipeline_id,
                user_id,
                stage_specs,
                initial_inputs,
            )
        else:
            input_blocks, input_connections = self._build_requirement_input_blocks(stage_specs, initial_inputs)

        stage_connections = self._build_stage_connections(stage_specs)
        output_blocks, output_connections = self._build_output_blocks(stage_specs, stage_status_map, output_files)

        blocks: List[Dict[str, Any]] = []
        blocks.extend(input_blocks)
        blocks.extend(stage_blocks)
        blocks.extend(output_blocks)
        blocks.sort(key=lambda block: (int(block.get("row") or 0), {"input": 0, "stage": 1, "output": 2}.get(str(block.get("column") or ""), 3), str(block.get("label") or "")))

        return {
            "job_id": job_id,
            "workflow_id": job.workflow_id,
            "latest_execution_id": latest_execution.id if latest_execution else None,
            "blocks": blocks,
            "connections": input_connections + stage_connections + output_connections,
        }

    def _build_visualization_specs_from_snapshot(self, snapshot_stages: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        specs: List[Dict[str, Any]] = []
        for item in snapshot_stages or []:
            if not isinstance(item, dict):
                continue
            stage_id = str(item.get("stage_id") or "").strip()
            if not stage_id:
                continue
            stage_kind = str(item.get("stage_kind") or "tool")
            tool_id = str(item.get("tool_id") or "")
            tool_name = str(item.get("tool_name") or tool_id or stage_id)
            stage_label = str(item.get("stage_label") or tool_name)
            specs.append(
                {
                    "stage_id": stage_id,
                    "stage_number": int(item.get("stage_number") or len(specs) + 1),
                    "stage_kind": stage_kind,
                    "dependency_ids": [str(dep).strip() for dep in (item.get("dependency_stage_ids") or []) if str(dep).strip()],
                    "stage_label": stage_label,
                    "result_labels": list(item.get("result_labels") or []),
                    "tool": {
                        "id": tool_id,
                        "name": tool_name,
                        "input_requirements": list(item.get("input_requirements") or []),
                        "produces": list(item.get("produces") or []),
                    },
                }
            )

        for index, spec in enumerate(specs):
            if spec.get("dependency_ids"):
                continue

            tool = spec.get("tool") or {}
            inferred_dependency_ids: List[str] = []
            for previous_spec in specs[:index]:
                previous_stage_id = str(previous_spec.get("stage_id") or "").strip()
                if not previous_stage_id:
                    continue
                previous_tool = previous_spec.get("tool") or {}
                if any(
                    self._tool_produces_requirement(previous_tool, str(requirement.get("type") or "").strip().lower())
                    for requirement in (tool.get("input_requirements") or [])
                ):
                    inferred_dependency_ids.append(previous_stage_id)
            spec["dependency_ids"] = inferred_dependency_ids

        return specs

    def _build_stage_description(self, spec: Dict[str, Any], stage_entry: Optional[Dict[str, Any]]) -> Optional[str]:
        if isinstance(stage_entry, dict):
            if stage_entry.get("error"):
                return str(stage_entry.get("error"))
            if stage_entry.get("output_count") is not None:
                count = int(stage_entry.get("output_count") or 0)
                return f"{count} output file{'s' if count != 1 else ''} recorded"

        dependency_ids = list(spec.get("dependency_ids") or [])
        if dependency_ids:
            return f"Depends on {len(dependency_ids)} upstream stage{'s' if len(dependency_ids) != 1 else ''}"

        if str(spec.get("stage_kind") or "tool") == "checkpoint":
            return "Pauses execution until resumed"

        return None

    def _normalize_visual_status(self, raw_status: str) -> str:
        normalized = str(raw_status or "").strip().lower()
        if normalized == "completed":
            return "finished"
        if normalized == "running":
            return "working"
        if normalized == "failed":
            return "failed"
        return "waiting"

    def _derive_output_status(self, producer_status: str, matching_outputs: List[Any]) -> str:
        normalized = str(producer_status or "").strip().lower()
        if normalized == "failed":
            return "failed"
        if matching_outputs or normalized == "completed":
            return "finished"
        if normalized == "running":
            return "working"
        return "waiting"

    def _humanize_token(self, value: str) -> str:
        text = str(value or "").strip().replace("_", " ")
        return " ".join(word.upper() if len(word) <= 3 else word.capitalize() for word in text.split())

    def _infer_artifact_formats(self, artifact: Dict[str, Any]) -> set[str]:
        formats: set[str] = set()
        file_format = artifact.get("file_format")
        if file_format:
            formats.add(str(file_format).lower().strip().lstrip("."))

        filename = str(artifact.get("filename") or "").lower()
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
        return formats

    def _artifact_matches_requirement(self, artifact: Dict[str, Any], requirement: Dict[str, Any]) -> bool:
        accepted_formats = {
            str(format_name).lower().strip().lstrip(".")
            for format_name in (requirement.get("formats") or [])
            if str(format_name).strip()
        }
        if not accepted_formats:
            return True
        return bool(self._infer_artifact_formats(artifact).intersection(accepted_formats))

    def _output_matches_stage(
        self,
        file_record: Any,
        tool: Dict[str, Any],
        produced_type: str,
    ) -> bool:
        filename = str(getattr(file_record, "filename", "") or "").lower()
        tool_name = str(tool.get("name") or tool.get("id") or "").lower()
        tool_id = str(tool.get("id") or "").lower()
        produced_token = str(produced_type or "").lower()

        if tool_id and tool_id != "checkpoint" and tool_id.lower() in filename:
            return True
        if tool_name and tool_name.lower() in filename:
            return True
        if produced_token and produced_token.replace("_", "") in filename.replace("_", ""):
            return True
        return False

    def _fits_job_budget(
        self,
        job_budget: Dict[str, int],
        reserved: Dict[str, int],
        tool_plan: Dict[str, Any],
    ) -> bool:
        usage = self._plan_usage(tool_plan)
        return (
            reserved["cpu_millis"] + usage["cpu_millis"] <= job_budget["cpu_millis"]
            and reserved["memory_mib"] + usage["memory_mib"] <= job_budget["memory_mib"]
            and (
                job_budget.get("storage_mib", 0) <= 0
                or reserved["storage_mib"] + usage["storage_mib"] <= job_budget["storage_mib"]
            )
        )

    def _single_stage_schedulable_plan(
        self,
        job_budget: Dict[str, int],
        reserved: Dict[str, int],
        tool_plan: Dict[str, Any],
    ) -> Dict[str, Any]:
        adjusted = dict(tool_plan)
        resources = dict(tool_plan.get("resources") or {})
        requests = dict(resources.get("requests") or {})
        resources["requests"] = requests
        adjusted["resources"] = resources

        available_cpu_millis = max(50, job_budget["cpu_millis"] - reserved["cpu_millis"])
        available_memory_mib = max(256, job_budget["memory_mib"] - reserved["memory_mib"])
        available_storage_mib = max(0, job_budget.get("storage_mib", 0) - reserved["storage_mib"])

        requested_cpu_millis = self._parse_cpu_quantity(str(requests.get("cpu") or "0"))
        requested_memory_mib = self._parse_memory_quantity_mib(str(requests.get("memory") or "0"))
        requested_storage_mib = self._parse_memory_quantity_mib(str(requests.get("ephemeral-storage") or "0"))

        if requested_cpu_millis <= 0 or requested_cpu_millis > available_cpu_millis:
            requests["cpu"] = self._format_cpu_quantity(available_cpu_millis)
        if requested_memory_mib <= 0 or requested_memory_mib > available_memory_mib:
            requests["memory"] = f"{available_memory_mib}Mi"
        if available_storage_mib > 0 and (requested_storage_mib <= 0 or requested_storage_mib > available_storage_mib):
            requests["ephemeral-storage"] = f"{available_storage_mib}Mi"

        adjusted["scheduler_request_adjusted"] = True
        return adjusted

    def _reserve_plan_resources(
        self,
        reserved: Dict[str, int],
        tool_plan: Dict[str, Any],
        direction: int,
    ) -> None:
        usage = self._plan_usage(tool_plan)
        reserved["cpu_millis"] = max(0, reserved["cpu_millis"] + direction * usage["cpu_millis"])
        reserved["memory_mib"] = max(0, reserved["memory_mib"] + direction * usage["memory_mib"])
        reserved["storage_mib"] = max(0, reserved["storage_mib"] + direction * usage["storage_mib"])

    def _build_initial_inputs(self, user_id: int, input_files: List[int]) -> List[Dict[str, Any]]:
        artifacts: List[Dict[str, Any]] = []
        for file_id in input_files:
            file_record = get_file_by_id(file_id, user_id=user_id)
            if not file_record:
                raise ValueError(f"File {file_id} not found")
            artifacts.append(
                {
                    "filename": file_record.filename,
                    "s3_key": file_record.s3_key,
                    "size_bytes": file_record.size_bytes or 0,
                    "file_format": getattr(file_record, "file_format", None),
                    "source": "job-input",
                    "producer_tool_id": None,
                }
            )
        return artifacts

    def _run_stage(
        self,
        job_id: int,
        execution_id: int,
        user_id: int,
        stage_number: int,
        tool: Dict[str, Any],
        stage_job_name: str,
        current_inputs: List[Dict[str, Any]],
        vm_name: Optional[str],
        stage_info: Dict[str, Any],
        parameters_used: Dict[str, Any],
        tool_plan: Optional[Dict[str, Any]] = None,
        tool_config: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        manifest = self._build_manifest(
            job_id=job_id,
            execution_id=execution_id,
            user_id=user_id,
            stage_number=stage_number,
            tool=tool,
            stage_job_name=stage_job_name,
            current_inputs=current_inputs,
            vm_name=vm_name,
            tool_plan=tool_plan,
            tool_config=tool_config,
        )
        namespace = self._config.kubernetes.namespace

        temp_manifest = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
        pod_name = ""
        try:
            json.dump(manifest, temp_manifest, indent=2)
            temp_manifest.close()

            apply_result = self._run_kubectl(["apply", "-f", temp_manifest.name], timeout=60)
            if apply_result.returncode != 0:
                raise RuntimeError(f"Failed to create Kubernetes Job {stage_job_name}: {apply_result.stderr.strip()}")

            stage_info["status"] = "running"
            pod_name = self._wait_for_stage_container(stage_job_name)
            stage_info["pod_name"] = pod_name

            logs = self._get_job_logs(stage_job_name)
            if logs:
                stage_info["logs_preview"] = logs[-2000:]
                stage_info["tool_logs_full"] = logs

            output_dir = self._copy_job_outputs(namespace, pod_name, tool["id"], stage_job_name)
            resource_usage = self._read_stage_resource_usage(output_dir)
            if resource_usage:
                stage_info.update(resource_usage)
            stage_outputs = self._upload_stage_outputs(
                local_output_dir=output_dir,
                job_id=job_id,
                execution_id=execution_id,
                user_id=user_id,
                stage_number=stage_number,
                tool=tool,
                current_inputs=current_inputs,
            )
            self._capture_stage_logs(stage_info, stage_job_name, pod_name=pod_name)
            log_artifacts = self._upload_stage_log_artifacts(
                stage_info=stage_info,
                job_id=job_id,
                execution_id=execution_id,
                user_id=user_id,
                stage_number=stage_number,
                tool=tool,
            )
            if log_artifacts:
                stage_outputs.extend(log_artifacts)

            return stage_outputs
        except Exception:
            self._capture_stage_logs(stage_info, stage_job_name, pod_name=pod_name)
            self._upload_stage_log_artifacts(
                stage_info=stage_info,
                job_id=job_id,
                execution_id=execution_id,
                user_id=user_id,
                stage_number=stage_number,
                tool=tool,
            )
            raise
        finally:
            try:
                os.unlink(temp_manifest.name)
            except Exception:
                pass
            self._run_kubectl(["delete", "job", stage_job_name, "-n", namespace, "--ignore-not-found=true"], timeout=60)

    def _build_manifest(
        self,
        job_id: int,
        execution_id: int,
        user_id: int,
        stage_number: int,
        tool: Dict[str, Any],
        stage_job_name: str,
        current_inputs: List[Dict[str, Any]],
        vm_name: Optional[str],
        tool_plan: Optional[Dict[str, Any]] = None,
        tool_config: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        config = self._config
        namespace = config.kubernetes.namespace
        minio_client = get_minio_client()
        minio_client.ensure_user_bucket(user_id=user_id)
        download_script = self._build_init_download_script(minio_client, user_id, current_inputs)
        tool_plan = tool_plan or self._plan_tool_resources(tool["id"], current_inputs, vm_name=vm_name)
        raw_tool_script = self._build_tool_script(tool, current_inputs, tool_plan, tool_config=tool_config)
        tool_script = self._wrap_tool_script_with_resource_capture(raw_tool_script)
        artifact_grace_seconds = self._env_int("CASSIE_ARTIFACT_SIDECAR_GRACE_SECONDS") or 600

        labels = {
            "app.kubernetes.io/name": "cassie-pipeline",
            "app.kubernetes.io/component": "tool-stage",
            "cassie/job-id": str(job_id),
            "cassie/execution-id": str(execution_id),
            "cassie/stage": str(stage_number),
            "cassie/tool-id": tool["id"].lower(),
        }

        return {
            "apiVersion": "batch/v1",
            "kind": "Job",
            "metadata": {
                "name": stage_job_name,
                "namespace": namespace,
                "labels": labels,
            },
            "spec": {
                "backoffLimit": 0,
                "template": {
                    "metadata": {"labels": labels},
                    "spec": {
                        "restartPolicy": "Never",
                        "volumes": [
                            {
                                "name": "workspace",
                                "emptyDir": {"sizeLimit": f'{tool_plan["storage_limit_mib"]}Mi'},
                            }
                        ],
                        "initContainers": [
                            {
                                "name": "fetch-inputs",
                                "image": config.kubernetes.aws_cli_image,
                                "command": ["sh", "-lc"],
                                "args": [download_script],
                                "env": [
                                    {"name": "AWS_ACCESS_KEY_ID", "value": config.minio.access_key},
                                    {"name": "AWS_SECRET_ACCESS_KEY", "value": config.minio.secret_key},
                                    {"name": "AWS_DEFAULT_REGION", "value": config.minio.region},
                                    {"name": "AWS_EC2_METADATA_DISABLED", "value": "true"},
                                    {
                                        "name": "S3_ENDPOINT",
                                        "value": self._cluster_visible_minio_endpoint(config.minio.endpoint),
                                    },
                                ],
                                "resources": {
                                    "requests": {
                                        "cpu": "50m",
                                        "memory": tool_plan["init_memory_request"],
                                        "ephemeral-storage": f'{tool_plan["init_storage_request_mib"]}Mi',
                                    },
                                    "limits": {
                                        "cpu": "500m",
                                        "memory": f'{tool_plan["init_memory_limit_mib"]}Mi',
                                        "ephemeral-storage": f'{tool_plan["storage_limit_mib"]}Mi',
                                    },
                                },
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                            }
                        ],
                        "containers": [
                            {
                                "name": "tool",
                                "image": tool.get("docker", {}).get("image"),
                                "imagePullPolicy": config.kubernetes.image_pull_policy,
                                "command": ["bash", "-lc"],
                                "args": [tool_script],
                                "resources": tool_plan["resources"],
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                            },
                            {
                                "name": "artifacts",
                                "image": "busybox:1.36.1",
                                "imagePullPolicy": "IfNotPresent",
                                "command": ["sh", "-lc"],
                                "args": [self._build_artifact_sidecar_script(artifact_grace_seconds)],
                                "resources": {
                                    "requests": {
                                        "cpu": "10m",
                                        "memory": "32Mi",
                                        "ephemeral-storage": "64Mi",
                                    },
                                    "limits": {
                                        "cpu": "100m",
                                        "memory": "128Mi",
                                        "ephemeral-storage": "512Mi",
                                    },
                                },
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                            },
                        ],
                    },
                },
            },
        }

    def _build_init_download_script(
        self,
        minio_client,
        user_id: int,
        current_inputs: List[Dict[str, Any]],
    ) -> str:
        lines = [
            "set -euo pipefail",
            "mkdir -p /workspace/input /workspace/output",
            "cassie_s3_cp() {",
            '  if [ -n "${S3_ENDPOINT:-}" ]; then',
            '    aws --endpoint-url "$S3_ENDPOINT" s3 cp "$1" "$2"',
            "  else",
            '    aws s3 cp "$1" "$2"',
            "  fi",
            "}",
        ]
        for artifact in current_inputs:
            filename = os.path.basename(artifact["filename"]).replace('"', '\\"')
            destination = f'/workspace/input/{filename}'
            lines.append("downloaded=0")
            for location in minio_client.get_read_locations(user_id=user_id, s3_key=artifact["s3_key"]):
                bucket_name = location["bucket"].replace('"', '\\"')
                object_key = location["key"].replace('"', '\\"')
                lines.extend(
                    [
                        f'if [ "$downloaded" -ne 1 ] && cassie_s3_cp "s3://{bucket_name}/{object_key}" "{destination}"; then',
                        "  downloaded=1",
                        "fi",
                    ]
                )
            original_key = str(artifact["s3_key"]).replace('"', '\\"')
            lines.extend(
                [
                    'if [ "$downloaded" -ne 1 ]; then',
                    f'  echo "Failed to download input {original_key} for user {user_id}" >&2',
                    "  exit 1",
                    "fi",
                ]
            )
        return "\n".join(lines)

    def _wrap_tool_script_with_resource_capture(self, tool_script: str) -> str:
        """Run the tool body and record cgroup CPU usage for model-training features."""
        return f"""set -uo pipefail
mkdir -p /workspace/output
cat > /tmp/cassie_tool_body.sh <<'__CASSIE_TOOL_BODY__'
{tool_script}
__CASSIE_TOOL_BODY__

cassie_cpu_usage_usec() {{
  if [ -r /sys/fs/cgroup/cpu.stat ]; then
    awk '$1 == "usage_usec" {{ print $2; found=1 }} END {{ if (!found) print 0 }}' /sys/fs/cgroup/cpu.stat
  else
    echo 0
  fi
}}

CASSIE_CPU_START="$(cassie_cpu_usage_usec || echo 0)"
CASSIE_WALL_START="$(date +%s)"
set +e
bash /tmp/cassie_tool_body.sh
CASSIE_STATUS=$?
CASSIE_WALL_END="$(date +%s)"
CASSIE_CPU_END="$(cassie_cpu_usage_usec || echo 0)"
CASSIE_CPU_DELTA=$(( CASSIE_CPU_END - CASSIE_CPU_START ))
if [ "$CASSIE_CPU_DELTA" -lt 0 ]; then
  CASSIE_CPU_DELTA=0
fi
CASSIE_WALL_DELTA=$(( CASSIE_WALL_END - CASSIE_WALL_START ))
printf '{{"cpu_usage_seconds": %s.%06d, "wall_time_seconds": %s, "source": "container_cgroup_cpu_stat"}}\\n' \
  "$(( CASSIE_CPU_DELTA / 1000000 ))" \
  "$(( CASSIE_CPU_DELTA % 1000000 ))" \
  "$CASSIE_WALL_DELTA" > /workspace/output/.cassie_resource_usage.json
exit "$CASSIE_STATUS"
"""

    def _wrap_tool_script(self, body_lines: List[str]) -> str:
        return "\n".join(
            [
                "set -euo pipefail",
                'rm -f /workspace/.tool-complete /workspace/.tool-exit-code',
                'trap \'status=$?; printf "%s\\n" "$status" > /workspace/.tool-exit-code; touch /workspace/.tool-complete; exit "$status"\' EXIT',
                *body_lines,
            ]
        )

    def _build_artifact_sidecar_script(self, grace_seconds: int) -> str:
        safe_grace_seconds = max(30, grace_seconds)
        return "\n".join(
            [
                "set -eu",
                "while [ ! -f /workspace/.tool-complete ]; do sleep 5; done",
                f"sleep {safe_grace_seconds}",
            ]
        )

    def _build_tool_script(
        self,
        tool: Dict[str, Any],
        current_inputs: List[Dict[str, Any]],
        tool_plan: Optional[Dict[str, Any]] = None,
        tool_config: Optional[Dict[str, Any]] = None,
    ) -> str:
        tool_plan = tool_plan or self._plan_tool_resources(tool["id"], current_inputs)
        tool_config = self._normalize_tool_config(tool["id"], tool_config)
        classified = self._classify_inputs(current_inputs)
        input_dir = "/workspace/input"
        output_dir = "/workspace/output"
        profile_note = (
            f'echo "CASSIE resource profile: {tool_plan["profile"]}; '
            f'threads={tool_plan["threads"]}; memory={tool_plan["memory_gb"]}G; '
            f'storage={tool_plan["storage_limit_mib"]}Mi; '
            f'available={tool_plan["available_cpu_millis"]}m CPU/{tool_plan["available_memory_mib"]}Mi memory"'
        )

        if tool["id"] == "FASTQC":
            reads = classified["fastq"]
            if not reads:
                raise ValueError("FastQC requires at least one FASTQ input file. FASTA files are not supported by FastQC.")
            fastqc_inputs = " ".join(
                f'"{input_dir}/{os.path.basename(read["filename"])}"'
                for read in reads
            )
            fastqc_flags: List[str] = []
            if tool_config.get("nogroup"):
                fastqc_flags.append("--nogroup")
            if tool_config.get("noextract"):
                fastqc_flags.append("--noextract")
            if tool_config.get("svg"):
                fastqc_flags.append("--svg")
            if tool_config.get("casava"):
                fastqc_flags.append("--casava")
            if tool_config.get("nano"):
                fastqc_flags.append("--nano")
            min_length = int(tool_config.get("min_length") or 0)
            requested_dup_length = int(tool_config.get("dup_length") or 0)
            if min_length > 0:
                fastqc_flags.append(f"--min_length {min_length}")
            fastqc_flag_str = f'{" ".join(fastqc_flags)} ' if fastqc_flags else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {output_dir}",
                    f'REQUESTED_DUP_LENGTH={requested_dup_length}',
                    'FASTQC_DUP_FLAG=""',
                    'if [ "${REQUESTED_DUP_LENGTH}" -gt 0 ]; then',
                    '  OBSERVED_MIN_READ_LENGTH=""',
                    f'  for fastqc_input in {fastqc_inputs}; do',
                    '    if printf "%s" "${fastqc_input}" | grep -q "\\.gz$"; then',
                    '      current_min=$(gzip -cd "${fastqc_input}" | awk \'NR % 4 == 2 { len = length($0); if (min == 0 || len < min) min = len; if (++count >= 200) { print min; exit } } END { if (min > 0) print min }\')',
                    '    else',
                    '      current_min=$(cat "${fastqc_input}" | awk \'NR % 4 == 2 { len = length($0); if (min == 0 || len < min) min = len; if (++count >= 200) { print min; exit } } END { if (min > 0) print min }\')',
                    '    fi',
                    '    if [ -n "${current_min}" ]; then',
                    '      if [ -z "${OBSERVED_MIN_READ_LENGTH}" ] || [ "${current_min}" -lt "${OBSERVED_MIN_READ_LENGTH}" ]; then',
                    '        OBSERVED_MIN_READ_LENGTH="${current_min}"',
                    '      fi',
                    '    fi',
                    '  done',
                    '  EFFECTIVE_DUP_LENGTH="${REQUESTED_DUP_LENGTH}"',
                    '  if [ -n "${OBSERVED_MIN_READ_LENGTH}" ] && [ "${OBSERVED_MIN_READ_LENGTH}" -lt "${EFFECTIVE_DUP_LENGTH}" ]; then',
                    '    EFFECTIVE_DUP_LENGTH="${OBSERVED_MIN_READ_LENGTH}"',
                    '  fi',
                    '  if [ "${EFFECTIVE_DUP_LENGTH}" -gt 0 ]; then',
                    '    FASTQC_DUP_FLAG="--dup_length ${EFFECTIVE_DUP_LENGTH}"',
                    '  fi',
                    'fi',
                    f'fastqc {fastqc_flag_str}${{FASTQC_DUP_FLAG}} --threads {tool_plan["threads"]} -o {output_dir} {fastqc_inputs}',
                ]
            )

        if tool["id"] == "SPADES":
            fastq_reads = self._select_fastq_inputs(classified["fastq"], required=2)
            if len(fastq_reads) < 2:
                raise ValueError("SPAdes requires paired-end reads (at least two FASTQ files)")
            r1 = os.path.basename(fastq_reads[0]["filename"])
            r2 = os.path.basename(fastq_reads[1]["filename"])
            threads = tool_plan["threads"]
            memory_gb = tool_plan["memory_gb"]
            low_resource = bool(tool_plan["low_resource"])
            user_only_assembler = bool(tool_config.get("only_assembler"))
            only_assembler_flag = " --only-assembler" if (low_resource or user_only_assembler) else ""
            careful_flag = " --careful" if bool(tool_config.get("careful")) else ""
            cov_cutoff = str(tool_config.get("cov_cutoff") or "off").strip()
            cov_cutoff_flag = (
                f" --cov-cutoff {cov_cutoff}"
                if cov_cutoff and cov_cutoff.lower() != "off"
                else " --cov-cutoff off"
            )
            phred_offset = str(tool_config.get("phred_offset") or "auto").strip()
            phred_offset_flag = f" --phred-offset {phred_offset}" if phred_offset in {"33", "64"} else ""
            kmers = str(tool_config.get("kmers") or tool_plan.get("kmers", "") or "").strip()
            kmers_flag = f" -k {kmers}" if kmers and re.fullmatch(r"\d+(,\d+)*", kmers) else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    "export TMPDIR=/workspace/tmp",
                    "mkdir -p /workspace/tmp",
                    f"mkdir -p {output_dir}/spades_out",
                    (
                        f'spades.py --threads {threads} --memory {memory_gb}{only_assembler_flag}{careful_flag}{cov_cutoff_flag}{phred_offset_flag}{kmers_flag} '
                        f'--tmp-dir /workspace/tmp '
                        f'-1 "{input_dir}/{r1}" -2 "{input_dir}/{r2}" '
                        f'-o "{output_dir}/spades_out"'
                    ),
                ]
            )

        if tool["id"] == "METASPADES":
            fastq_reads = self._select_fastq_inputs(classified["fastq"], required=2)
            if len(fastq_reads) < 2:
                raise ValueError("metaSPAdes requires paired-end reads (at least two FASTQ files)")
            r1 = os.path.basename(fastq_reads[0]["filename"])
            r2 = os.path.basename(fastq_reads[1]["filename"])
            low_resource = bool(tool_plan["low_resource"])
            only_assembler_flag = " --only-assembler" if (low_resource or bool(tool_config.get("only_assembler"))) else ""
            phred_offset = str(tool_config.get("phred_offset") or "auto").strip()
            phred_offset_flag = f" --phred-offset {phred_offset}" if phred_offset in {"33", "64"} else ""
            kmers = str(tool_config.get("kmers") or ("21" if low_resource else "")).strip()
            kmers_flag = f" -k {kmers}" if kmers and re.fullmatch(r"\d+(,\d+)*", kmers) else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    "export TMPDIR=/workspace/tmp",
                    "mkdir -p /workspace/tmp",
                    f"mkdir -p {output_dir}/metaspades_out",
                    (
                        f'spades.py --meta --threads {tool_plan["threads"]} --memory {tool_plan["memory_gb"]}{only_assembler_flag}{phred_offset_flag}{kmers_flag} '
                        f'--tmp-dir /workspace/tmp '
                        f'-1 "{input_dir}/{r1}" -2 "{input_dir}/{r2}" '
                        f'-o "{output_dir}/metaspades_out"'
                    ),
                ]
            )

        if tool["id"] == "QUAST":
            assembly, reference = self._resolve_quast_inputs(classified["fasta"])
            threads = tool_plan["threads"]
            quast_flags: List[str] = []
            min_contig = int(tool_config.get("min_contig") or 0)
            if min_contig > 0:
                quast_flags.append(f"--min-contig {min_contig}")
            if tool_config.get("gene_finding"):
                quast_flags.append("--gene-finding")
            if tool_config.get("large"):
                quast_flags.append("--large")
            if tool_config.get("fragmented"):
                quast_flags.append("--fragmented")
            if tool_plan["low_resource"] or tool_config.get("memory_efficient"):
                quast_flags.append("--memory-efficient")
            quast_flag_str = f'{" ".join(quast_flags)} ' if quast_flags else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {output_dir}/quast_out",
                    f'quast.py "{input_dir}/{os.path.basename(assembly["filename"])}" '
                    f'-r "{input_dir}/{os.path.basename(reference["filename"])}" '
                    f'{quast_flag_str}-t {threads} -o "{output_dir}/quast_out"',
                ]
            )

        if tool["id"] == "GENOMESCOPE2":
            fastq_reads = classified["fastq"]
            if not fastq_reads:
                raise ValueError("GenomeScope2 requires FASTQ reads")
            threads = tool_plan["threads"]
            inputs = [os.path.basename(item["filename"]) for item in fastq_reads]
            stream_commands: List[str] = []
            for input_name in inputs:
                src = f"{input_dir}/{input_name}"
                if input_name.lower().endswith(".gz"):
                    stream_commands.append(f'zcat "{src}"')
                else:
                    stream_commands.append(f'cat "{src}"')

            stream_expr = "; ".join(stream_commands)
            jellyfish_size = str(tool_config.get("jellyfish_hash_size") or tool_plan.get("jellyfish_size", "50M"))
            kmer_length = int(tool_config.get("kmer_length") or 21)
            ploidy = int(tool_config.get("ploidy") or 1)
            initial_coverage = int(tool_config.get("initial_coverage") or 0)
            max_kmer_coverage = int(tool_config.get("max_kmer_coverage") or 0)
            gs_out = f"{output_dir}/genomescope2_out"
            optional_fit_flags = []
            if initial_coverage > 0:
                optional_fit_flags.append(f"-l {initial_coverage}")
            if max_kmer_coverage > 0:
                optional_fit_flags.append(f"-m {max_kmer_coverage}")
            optional_fit_flag_str = f' {" ".join(optional_fit_flags)}' if optional_fit_flags else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {gs_out}",
                    (
                        f'jellyfish count -C -m {kmer_length} -s {jellyfish_size} -t {threads} '
                        f'<({stream_expr}) -o "{gs_out}/reads.jf"'
                    ),
                    f'jellyfish histo "{gs_out}/reads.jf" > "{gs_out}/reads.histo"',
                    f'Rscript /opt/genomescope2.0/genomescope.R -i "{gs_out}/reads.histo" -o "{gs_out}" -k {kmer_length} -p {ploidy}{optional_fit_flag_str}',
                ]
            )

        if tool["id"] == "HIFIASM":
            hifi_reads = classified["reads_like"]
            if not hifi_reads:
                raise ValueError("Hifiasm requires HiFi reads in FASTQ or FASTA format")
            hifiasm_inputs = self._quoted_input_paths(input_dir, hifi_reads)
            hifiasm_out = f"{output_dir}/hifiasm_out"
            prefix = f"{hifiasm_out}/assembly"
            hifiasm_flags: List[str] = []
            low_resource = bool(tool_plan.get("low_resource"))
            if str(tool_config.get("mode") or "hifi").strip().lower() == "ont":
                hifiasm_flags.append("--ont")
            if low_resource or tool_config.get("disable_dup_purging"):
                hifiasm_flags.append("-l0")
            trim_bp = int(tool_config.get("trim_bp") or 0)
            if trim_bp > 0:
                hifiasm_flags.append(f"-z{trim_bp}")
            if low_resource or tool_config.get("small_genome_no_bloom"):
                hifiasm_flags.append("-f0")
            if tool_config.get("write_paf"):
                hifiasm_flags.append("--write-paf")
            hifiasm_flag_str = f'{" ".join(hifiasm_flags)} ' if hifiasm_flags else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {hifiasm_out}",
                    (
                        f'hifiasm {hifiasm_flag_str}-o "{prefix}" -t {tool_plan["threads"]} {hifiasm_inputs} '
                        f'2> "{hifiasm_out}/hifiasm.log"'
                    ),
                    f'PRIMARY_GFA="$(find "{hifiasm_out}" -maxdepth 1 -type f \\( -name "assembly*.bp.p_ctg.gfa" -o -name "assembly*.p_ctg.gfa" \\) | head -n 1)"',
                    'if [ -z "${PRIMARY_GFA}" ]; then echo "Could not find Hifiasm primary contig GFA output" >&2; exit 1; fi',
                    f'awk \'/^S/{{print ">"$2;print $3}}\' "${{PRIMARY_GFA}}" > "{hifiasm_out}/assembly.primary.fasta"',
                ]
            )

        if tool["id"] == "VERKKO":
            hifi_reads, nano_reads = self._split_verkko_reads(classified["reads_like"])
            if not hifi_reads:
                raise ValueError("Verkko requires at least one HiFi long-read FASTQ/FASTA input")
            verkko_out = f"{output_dir}/verkko_out"
            hifi_args = self._quoted_input_paths(input_dir, hifi_reads)
            nano_flag = ""
            if nano_reads:
                nano_flag = f" --nano {self._quoted_input_paths(input_dir, nano_reads)}"
            extra_flags = []
            if tool_config.get("haploid"):
                extra_flags.append("--haploid")
            if tool_config.get("uneven_depth"):
                extra_flags.append("--uneven-depth")
            telomere_motif = str(tool_config.get("telomere_motif") or "").strip()
            if telomere_motif:
                extra_flags.append(f'--telomere-motif {telomere_motif}')
            extra_flag_str = f' {" ".join(extra_flags)}' if extra_flags else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {verkko_out}",
                    (
                        f'verkko -d "{verkko_out}" --hifi {hifi_args}{nano_flag}{extra_flag_str} '
                        f'--snakeopts "--cores {tool_plan["threads"]}"'
                    ),
                ]
            )

        if tool["id"] == "LIFTOFF":
            target, reference = self._resolve_target_reference_genomes(classified["fasta"])
            annotation = self._resolve_annotation_input(classified["annotation"])
            liftoff_out = f"{output_dir}/liftoff_out"
            liftoff_flags: List[str] = []
            liftoff_flags.append(f'-a {tool_config.get("coverage_threshold")}')
            liftoff_flags.append(f'-s {tool_config.get("identity_threshold")}')
            liftoff_flags.append(f'-flank {tool_config.get("flank_fraction")}')
            if tool_config.get("exclude_partial"):
                liftoff_flags.append("-exclude_partial")
            if tool_config.get("copies"):
                liftoff_flags.append("-copies")
            liftoff_flag_str = " ".join(liftoff_flags)
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {liftoff_out}",
                    (
                        f'liftoff -p {tool_plan["threads"]} '
                        f'{liftoff_flag_str} '
                        f'-g "{input_dir}/{os.path.basename(annotation["filename"])}" '
                        f'-o "{liftoff_out}/liftoff.gff3" '
                        f'"{input_dir}/{os.path.basename(target["filename"])}" '
                        f'"{input_dir}/{os.path.basename(reference["filename"])}" '
                        f'> "{liftoff_out}/liftoff.stdout.log" 2> "{liftoff_out}/liftoff.stderr.log"'
                    ),
                ]
            )

        if tool["id"] == "CAT":
            hal_alignment = self._resolve_single_artifact(classified["hal"], "CAT requires a HAL alignment input")
            annotation = self._resolve_annotation_input(classified["annotation"])
            reference_name = self._resolve_single_artifact(
                classified["text"],
                "CAT requires a text file containing the reference genome name present in the HAL alignment",
            )
            cat_out = f"{output_dir}/cat_out"
            cat_work = f"{output_dir}/cat_work"
            cat_config = f"{output_dir}/generated.cat.ini"
            cat_flags: List[str] = ['--local-scheduler']
            if tool_config.get("augustus"):
                cat_flags.append("--augustus")
            augustus_species = str(tool_config.get("augustus_species") or "").strip()
            if augustus_species:
                cat_flags.append(f'--augustus-species "{augustus_species}"')
            if tool_config.get("augustus_utr_off"):
                cat_flags.append("--augustus-utr-off")
            if tool_config.get("assembly_hub"):
                cat_flags.append("--assembly-hub")
            cat_flag_str = " ".join(cat_flags)
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {cat_out} {cat_work}",
                    f'REF_NAME="$(tr -d \'\\r\\n\' < "{input_dir}/{os.path.basename(reference_name["filename"])}")"',
                    'if [ -z "${REF_NAME}" ]; then echo "CAT reference genome name file is empty" >&2; exit 1; fi',
                    f'printf "[ANNOTATION]\\n%s = %s\\n" "${{REF_NAME}}" "{input_dir}/{os.path.basename(annotation["filename"])}" > "{cat_config}"',
                    (
                        f'luigi --module cat RunCat '
                        f'--hal "{input_dir}/{os.path.basename(hal_alignment["filename"])}" '
                        f'--ref-genome "${{REF_NAME}}" '
                        f'--config "{cat_config}" '
                        f'--binary-mode local '
                        f'--workers {tool_plan["threads"]} '
                        f'--out-dir "{cat_out}" '
                        f'--work-dir "{cat_work}" '
                        f'{cat_flag_str}'
                    ),
                ]
            )

        if tool["id"] == "BUSCO":
            assembly = self._resolve_busco_input(classified["fasta"])
            busco_out = f"{output_dir}/busco_out"
            configured_lineage = str(tool_config.get("lineage_dataset") or "").strip()
            default_lineage = configured_lineage or self._config.tools.busco_default_lineage
            download_path = self._config.tools.busco_download_path
            lineage_dir = f'{download_path.rstrip("/")}/lineages/{default_lineage}'
            busco_mode = str(tool_config.get("mode") or "genome").strip()
            auto_lineage = str(tool_config.get("auto_lineage") or "off").strip()
            busco_extra_flags: List[str] = []
            if auto_lineage == "auto-lineage":
                busco_extra_flags.append("--auto-lineage")
            elif auto_lineage == "auto-lineage-euk":
                busco_extra_flags.append("--auto-lineage-euk")
            elif auto_lineage == "auto-lineage-prok":
                busco_extra_flags.append("--auto-lineage-prok")
            else:
                busco_extra_flags.append(f'-l "${{BUSCO_LINEAGE}}"')
            if tool_config.get("augustus"):
                busco_extra_flags.append("--augustus")
            augustus_species = str(tool_config.get("augustus_species") or "").strip()
            if augustus_species:
                busco_extra_flags.append(f'--augustus_species {augustus_species}')
            busco_extra_flag_str = " ".join(busco_extra_flags)
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {busco_out}",
                    f'BUSCO_DOWNLOAD_PATH="{download_path}"',
                    f'BUSCO_LINEAGE="{lineage_dir}"',
                    'if [ ! -d "${BUSCO_LINEAGE}" ]; then',
                    '  echo "BUSCO lineage ${BUSCO_LINEAGE} is not cached; downloading it now..." >&2',
                    f'  busco --download_path "${{BUSCO_DOWNLOAD_PATH}}" --download "{default_lineage}"',
                    'fi',
                    (
                        f'cd "{busco_out}" && '
                        f'busco -i "{input_dir}/{os.path.basename(assembly["filename"])}" '
                        f'-m {busco_mode} {busco_extra_flag_str} '
                        f'--download_path "${{BUSCO_DOWNLOAD_PATH}}" --offline '
                        f'-c {tool_plan["threads"]} -o busco_run'
                    ),
                ]
            )

        if tool["id"] == "MERQURY":
            assembly = self._resolve_busco_input(classified["fasta"])
            meryl_input = self._resolve_single_artifact(
                classified["meryl"],
                "Merqury requires a .meryl.tar.gz or .meryl.tgz database archive",
            )
            merqury_out = f"{output_dir}/merqury_out"
            meryl_name = os.path.basename(meryl_input["filename"])
            meryl_source = f"{input_dir}/{meryl_name}"
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {merqury_out} /workspace/meryl_db",
                    f'MERYL_SRC="{meryl_source}"',
                    'MERQURY_DB="${MERYL_SRC}"',
                    'if [ ! -d "${MERQURY_DB}" ]; then',
                    '  case "${MERYL_SRC}" in',
                    '    *.tar.gz|*.tgz) tar -xzf "${MERYL_SRC}" -C /workspace/meryl_db ;;',
                    '    *.tar) tar -xf "${MERYL_SRC}" -C /workspace/meryl_db ;;',
                    '    *) echo "Unsupported Merqury database input. Upload a .meryl.tar.gz or .meryl.tgz archive." >&2; exit 1 ;;',
                    '  esac',
                    '  FOUND_DB="$(find /workspace/meryl_db -maxdepth 3 -type d -name "*.meryl" | head -n 1)"',
                    '  if [ -n "${FOUND_DB}" ]; then MERQURY_DB="${FOUND_DB}"; fi',
                    'fi',
                    'if [ ! -d "${MERQURY_DB}" ]; then echo "Could not locate a .meryl database directory for Merqury" >&2; exit 1; fi',
                    (
                        f'merqury.sh "${{MERQURY_DB}}" '
                        f'"{input_dir}/{os.path.basename(assembly["filename"])}" '
                        f'"{merqury_out}"'
                    ),
                ]
            )

        raise ValueError(f"Kubernetes runner does not yet support tool {tool['id']}")

    def _normalize_tool_config(self, tool_id: str, tool_config: Optional[Dict[str, Any]]) -> Dict[str, Any]:
        validation = validate_tool_flag_values(tool_id, tool_config or {})
        if validation["errors"]:
            raise ValueError(
                f"Invalid configuration for {tool_id}: "
                + "; ".join(f"{key}: {value}" for key, value in validation["errors"].items())
            )
        return validation["values"]

    def _quoted_input_paths(self, input_dir: str, artifacts: List[Dict[str, Any]]) -> str:
        return " ".join(f'"{input_dir}/{os.path.basename(item["filename"])}"' for item in artifacts)

    def _resolve_single_artifact(self, artifacts: List[Dict[str, Any]], error_message: str) -> Dict[str, Any]:
        if not artifacts:
            raise ValueError(error_message)
        return artifacts[0]

    def _is_assembly_artifact(self, artifact: Dict[str, Any]) -> bool:
        filename = str(artifact.get("filename") or "").lower()
        producer = str(artifact.get("producer_tool_id") or "").upper()
        if producer in {"SPADES", "METASPADES", "HIFIASM", "VERKKO"}:
            return True
        return any(token in filename for token in ("contig", "scaffold", "assembly", "primary", "consensus"))

    def _resolve_busco_input(self, fasta_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not fasta_files:
            raise ValueError("This tool requires at least one FASTA assembly/genome input")
        for artifact in fasta_files:
            if self._is_assembly_artifact(artifact):
                return artifact
        return fasta_files[0]

    def _resolve_target_reference_genomes(self, fasta_files: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if len(fasta_files) < 2:
            raise ValueError("This tool requires both a target genome FASTA and a reference genome FASTA")
        target = self._resolve_busco_input(fasta_files)
        reference = next((artifact for artifact in fasta_files if artifact["filename"] != target["filename"]), None)
        if reference is None:
            raise ValueError("Could not determine the reference genome FASTA input")
        return target, reference

    def _resolve_annotation_input(self, annotation_files: List[Dict[str, Any]]) -> Dict[str, Any]:
        if not annotation_files:
            raise ValueError("This tool requires an annotation file in GFF/GFF3/GTF format")
        preferred = sorted(
            annotation_files,
            key=lambda item: (
                0 if str(item.get("filename") or "").lower().endswith(".gff3") else 1,
                str(item.get("filename") or "").lower(),
            ),
        )
        return preferred[0]

    def _split_verkko_reads(self, read_files: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        if not read_files:
            return [], []
        nano_reads: List[Dict[str, Any]] = []
        hifi_reads: List[Dict[str, Any]] = []
        for artifact in read_files:
            lowered = str(artifact.get("filename") or "").lower()
            if any(token in lowered for token in ("ont", "nano", "ultra", "ul_")):
                nano_reads.append(artifact)
            else:
                hifi_reads.append(artifact)
        if not hifi_reads:
            hifi_reads = list(read_files)
            nano_reads = []
        return hifi_reads, nano_reads

    def _tool_threads(self, tool_id: str, default: int) -> int:
        if not self._resource_env_overrides_enabled():
            return max(1, default)
        raw_value = os.getenv(f"{tool_id}_THREADS", os.getenv("CASSIE_TOOL_THREADS", str(default))).strip()
        try:
            return max(1, int(raw_value))
        except ValueError:
            return default

    def _tool_memory_gb(self, tool_id: str, default: int) -> int:
        if not self._resource_env_overrides_enabled():
            return max(1, default)
        raw_value = os.getenv(f"{tool_id}_MEMORY_GB", os.getenv("CASSIE_TOOL_MEMORY_GB", str(default))).strip()
        try:
            return max(1, int(raw_value))
        except ValueError:
            return default

    def _resource_env_overrides_enabled(self) -> bool:
        return os.getenv("CASSIE_ALLOW_RESOURCE_ENV_OVERRIDES", "false").strip().lower() in {"1", "true", "yes", "on"}

    def _dynamic_threads(self, whole_cpus: int, ratio: float = 0.8) -> int:
        """Size tool threads from the selected VM partition CPU budget."""
        return max(1, min(whole_cpus, int(max(1, whole_cpus * ratio))))

    def _dynamic_memory_gb(self, memory_mib: int, ratio: float = 0.75, reserve_mib: int = 0) -> int:
        """Size tool memory from the selected VM partition memory budget."""
        usable_mib = max(1024, memory_mib - max(0, reserve_mib))
        return max(1, int((usable_mib * ratio) // 1024))

    def _cpu_limit_for_threads(self, threads: int, cpu_millis: int) -> int:
        """Give a multithreaded tool enough CPU to use its planned thread count."""
        return min(max(250, threads * 1000), max(1, cpu_millis))

    def _tool_flag(self, env_name: str, default: bool) -> bool:
        raw_value = os.getenv(env_name)
        if raw_value is None:
            return default
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}

    def _plan_tool_resources(
        self,
        tool_id: str,
        current_inputs: Optional[List[Dict[str, Any]]] = None,
        vm_name: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Choose the strongest safe tool profile for the current cluster."""
        capacity = self._detect_effective_cluster_capacity(vm_name=vm_name)
        cpu_millis = max(1, capacity["cpu_millis"])
        memory_mib = max(1, capacity["memory_mib"])
        tool_memory_budget_mib = memory_mib
        whole_cpus = max(1, cpu_millis // 1000)
        resource_mode = os.getenv("CASSIE_RESOURCE_MODE", "adaptive").strip().lower()
        input_size_mib = self._estimate_input_size_mib(current_inputs or [])
        default_threads = self._dynamic_threads(whole_cpus, ratio=0.85)
        default_memory_gb = self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.85)

        if tool_id == "SPADES":
            forced_low_resource = self._env_bool_or_none("SPADES_LOW_RESOURCE")
            if resource_mode == "conservative":
                low_resource = True
            elif resource_mode == "full":
                low_resource = False
            elif forced_low_resource is not None:
                low_resource = forced_low_resource
            else:
                low_resource = memory_mib < 6144 or whole_cpus < 4

            default_threads = 1 if low_resource else self._dynamic_threads(whole_cpus, ratio=0.9)
            default_memory_gb = 2 if low_resource else self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.85, reserve_mib=512)
            default_kmers = "21" if low_resource else ""
            profile = "low-resource" if low_resource else "full"

            if self._tool_flag("SPADES_REQUIRE_FULL", default=False) and low_resource:
                raise RuntimeError(
                    "SPAdes full correction mode does not fit the currently detected Kubernetes resources "
                    f"({cpu_millis}m CPU, {memory_mib}Mi memory). Increase Minikube/Docker resources or "
                    "unset SPADES_REQUIRE_FULL to allow low-resource assembly mode."
                )

            threads = self._tool_threads(tool_id, default_threads)
            memory_gb = min(self._tool_memory_gb(tool_id, default_memory_gb), max(1, tool_memory_budget_mib // 1024))
            memory_limit = min(
                tool_memory_budget_mib,
                max((memory_gb * 1024) + 512, 2560 if low_resource else 6144),
            )
            kmers = self._env_value_or_default("SPADES_KMERS", default_kmers)

            return self._resource_plan(
                tool_id=tool_id,
                profile=profile,
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=low_resource,
                kmers=kmers,
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "METASPADES":
            low_resource = memory_mib < 6144 or whole_cpus < 4
            threads = self._tool_threads(tool_id, 1 if low_resource else self._dynamic_threads(whole_cpus, ratio=0.9))
            memory_gb = min(
                self._tool_memory_gb(tool_id, 2 if low_resource else self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.8, reserve_mib=512)),
                max(1, tool_memory_budget_mib // 1024),
            )
            memory_limit = min(tool_memory_budget_mib, max((memory_gb * 1024) + 512, 2560 if low_resource else 5120))
            return self._resource_plan(
                tool_id=tool_id,
                profile="low-resource" if low_resource else "full",
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=low_resource,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "GENOMESCOPE2":
            requested_threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.7) if memory_mib >= 4096 else 1)
            requested_memory_gb = self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.65 if memory_mib >= 4096 else 0.5)
            memory_limit = min(tool_memory_budget_mib, max(2048, requested_memory_gb * 1024))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=requested_threads,
                memory_gb=requested_memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(requested_threads, cpu_millis),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
                extra={"jellyfish_size": self._genomescope_hash_size(memory_limit)},
            )

        if tool_id == "QUAST":
            requested_threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.75) if memory_mib >= 4096 else 1)
            requested_memory_gb = self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.6 if memory_mib >= 4096 else 0.5)
            memory_limit = min(tool_memory_budget_mib, max(1536, requested_memory_gb * 1024))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=requested_threads,
                memory_gb=requested_memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(requested_threads, cpu_millis),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "FASTQC":
            requested_threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.75) if memory_mib >= 4096 else 1)
            requested_memory_gb = self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.4 if memory_mib >= 4096 else 0.5)
            memory_limit = min(tool_memory_budget_mib, max(2048, requested_memory_gb * 1024))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=requested_threads,
                memory_gb=requested_memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(requested_threads, cpu_millis),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "HIFIASM":
            low_resource = memory_mib < 8192 or whole_cpus < 4
            threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.9) if not low_resource else self._dynamic_threads(whole_cpus, ratio=0.5))
            memory_gb = min(
                self._tool_memory_gb(tool_id, 4 if low_resource else self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.8, reserve_mib=512)),
                max(1, tool_memory_budget_mib // 1024),
            )
            memory_limit = min(tool_memory_budget_mib, max((memory_gb * 1024) + 512, 4096))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=low_resource,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "VERKKO":
            low_resource = memory_mib < 8192 or whole_cpus < 4
            threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.9) if not low_resource else self._dynamic_threads(whole_cpus, ratio=0.5))
            memory_gb = min(
                self._tool_memory_gb(tool_id, 6 if low_resource else self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.85, reserve_mib=1024)),
                max(1, tool_memory_budget_mib // 1024),
            )
            memory_limit = min(tool_memory_budget_mib, max((memory_gb * 1024) + 1024, 6144))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=low_resource,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "LIFTOFF":
            threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.75))
            memory_gb = min(self._tool_memory_gb(tool_id, self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.55)), max(1, tool_memory_budget_mib // 1024))
            memory_limit = min(tool_memory_budget_mib, max((memory_gb * 1024) + 256, 2048))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "CAT":
            low_resource = memory_mib < 6144
            threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.5) if low_resource else self._dynamic_threads(whole_cpus, ratio=0.8))
            memory_gb = min(
                self._tool_memory_gb(tool_id, 4 if low_resource else self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.75, reserve_mib=512)),
                max(1, tool_memory_budget_mib // 1024),
            )
            memory_limit = min(tool_memory_budget_mib, max((memory_gb * 1024) + 512, 4096))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=low_resource,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "BUSCO":
            threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.8))
            memory_gb = min(self._tool_memory_gb(tool_id, self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.65)), max(1, tool_memory_budget_mib // 1024))
            memory_limit = min(tool_memory_budget_mib, max((memory_gb * 1024) + 256, 2048))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "MERQURY":
            threads = self._tool_threads(tool_id, self._dynamic_threads(whole_cpus, ratio=0.7))
            memory_gb = min(self._tool_memory_gb(tool_id, self._dynamic_memory_gb(tool_memory_budget_mib, ratio=0.75)), max(1, tool_memory_budget_mib // 1024))
            memory_limit = min(tool_memory_budget_mib, max((memory_gb * 1024) + 256, 2048))
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=self._cpu_limit_for_threads(threads, cpu_millis),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        requested_threads = self._tool_threads(tool_id, default_threads)
        requested_memory_gb = self._tool_memory_gb(tool_id, default_memory_gb)
        memory_limit = min(tool_memory_budget_mib, max(1024, requested_memory_gb * 1024))
        return self._resource_plan(
            tool_id=tool_id,
            profile="adaptive",
            threads=requested_threads,
            memory_gb=requested_memory_gb,
            memory_limit_mib=memory_limit,
            cpu_limit_millis=self._cpu_limit_for_threads(requested_threads, cpu_millis),
            low_resource=False,
            kmers="",
            input_size_mib=input_size_mib,
            capacity=capacity,
        )

    def _resource_plan(
        self,
        tool_id: str,
        profile: str,
        threads: int,
        memory_gb: int,
        memory_limit_mib: int,
        cpu_limit_millis: int,
        low_resource: bool,
        kmers: str,
        input_size_mib: int,
        capacity: Dict[str, int],
        extra: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        prefix = tool_id.upper()
        storage_limit_mib = self._tool_storage_limit_mib(
            tool_id=tool_id,
            input_size_mib=input_size_mib,
            low_resource=low_resource,
            capacity=capacity,
        )
        storage_request_mib = min(
            storage_limit_mib,
            max(256, input_size_mib + (512 if tool_id == "SPADES" else 256)),
        )
        init_storage_request_mib = min(storage_limit_mib, max(128, input_size_mib + 128))
        init_memory_limit_mib = min(
            capacity["memory_mib"],
            max(768, memory_limit_mib, input_size_mib + 384),
        )
        init_memory_request_mib = self._init_memory_request_mib(
            tool_id=tool_id,
            memory_limit_mib=memory_limit_mib,
            init_memory_limit_mib=init_memory_limit_mib,
            capacity=capacity,
        )
        init_memory_request = f"{init_memory_request_mib}Mi"
        cpu_limit = self._format_cpu_quantity(cpu_limit_millis)
        memory_limit = f"{memory_limit_mib}Mi"
        storage_limit = f"{storage_limit_mib}Mi"
        if self._resource_env_overrides_enabled():
            cpu_limit = self._env_value_or_default(f"{prefix}_CPU_LIMIT", cpu_limit)
            memory_limit = self._env_value_or_default(f"{prefix}_MEMORY_LIMIT", memory_limit)
            storage_limit = self._env_value_or_default(f"{prefix}_STORAGE_LIMIT", storage_limit)
        hard_cpu_request = cpu_limit
        hard_memory_request = memory_limit
        hard_storage_request = storage_limit

        plan = {
            "profile": profile,
            "threads": max(1, threads),
            "memory_gb": max(1, memory_gb),
            "memory_limit_mib": memory_limit_mib,
            "cpu_limit_millis": cpu_limit_millis,
            "low_resource": low_resource,
            "kmers": kmers,
            "input_size_mib": input_size_mib,
            "storage_limit_mib": storage_limit_mib,
            "storage_request_mib": storage_request_mib,
            "init_storage_request_mib": init_storage_request_mib,
            "init_memory_limit_mib": init_memory_limit_mib,
            "init_memory_request_mib": init_memory_request_mib,
            "init_memory_request": init_memory_request,
            "storage_constrained": storage_limit_mib < self._estimated_required_storage_mib(
                tool_id, input_size_mib, low_resource
            ),
            "available_cpu_millis": capacity["cpu_millis"],
            "available_memory_mib": capacity["memory_mib"],
            "available_storage_mib": capacity.get("storage_mib", 0),
            "resources": {
                "requests": {
                    "cpu": hard_cpu_request,
                    "memory": hard_memory_request,
                    "ephemeral-storage": hard_storage_request,
                },
                "limits": {
                    "cpu": cpu_limit,
                    "memory": memory_limit,
                    "ephemeral-storage": storage_limit,
                },
            },
        }
        if extra:
            plan.update(extra)
        return plan

    def _estimate_input_size_mib(self, current_inputs: List[Dict[str, Any]]) -> int:
        total_bytes = 0
        for artifact in current_inputs:
            try:
                total_bytes += int(artifact.get("size_bytes") or 0)
            except (TypeError, ValueError):
                continue
        if total_bytes <= 0:
            return 0
        return max(1, (total_bytes + (1024 * 1024) - 1) // (1024 * 1024))

    def _estimated_required_storage_mib(self, tool_id: str, input_size_mib: int, low_resource: bool) -> int:
        padded_input = max(256, input_size_mib)
        if tool_id == "SPADES":
            multiplier = 3 if low_resource else 5
            return max(4096, padded_input * multiplier + 2048)
        if tool_id == "METASPADES":
            multiplier = 3 if low_resource else 4
            return max(4096, padded_input * multiplier + 2048)
        if tool_id == "HIFIASM":
            return max(4096, padded_input * 3 + 2048)
        if tool_id == "VERKKO":
            return max(6144, padded_input * 4 + 4096)
        if tool_id == "GENOMESCOPE2":
            return max(2048, padded_input + 2048)
        if tool_id == "QUAST":
            return max(1536, padded_input * 2 + 1024)
        if tool_id == "LIFTOFF":
            return max(2048, padded_input * 2 + 1024)
        if tool_id == "CAT":
            return max(4096, padded_input * 3 + 2048)
        if tool_id == "BUSCO":
            return max(2048, padded_input * 2 + 2048)
        if tool_id == "MERQURY":
            return max(3072, padded_input * 2 + 2048)
        return max(1024, padded_input + 1024)

    def _tool_storage_limit_mib(
        self,
        tool_id: str,
        input_size_mib: int,
        low_resource: bool,
        capacity: Dict[str, int],
    ) -> int:
        prefix = tool_id.upper()
        explicit_limit = self._env_int(f"{prefix}_STORAGE_MIB") or self._env_int("CASSIE_TOOL_STORAGE_MIB")
        if explicit_limit > 0:
            return explicit_limit

        required_mib = self._estimated_required_storage_mib(tool_id, input_size_mib, low_resource)
        cluster_storage_mib = capacity.get("storage_mib", 0)
        if cluster_storage_mib <= 0:
            return max(required_mib, 4096)

        max_workspace_mib = max(1024, cluster_storage_mib)
        return min(max_workspace_mib, max(required_mib, 1024))

    def _init_memory_request_mib(
        self,
        tool_id: str,
        memory_limit_mib: int,
        init_memory_limit_mib: int,
        capacity: Dict[str, int],
    ) -> int:
        prefix = tool_id.upper()
        explicit_request = self._env_int(f"{prefix}_INIT_MEMORY_REQUEST_MIB") or self._env_int(
            "CASSIE_INIT_MEMORY_REQUEST_MIB"
        )
        if explicit_request > 0:
            requested_mib = explicit_request
        else:
            requested_mib = min(512, max(256, memory_limit_mib // 8))

        reserve_mib = self._env_int("CASSIE_CLUSTER_MEMORY_RESERVE_MIB") or 256
        schedulable_mib = max(128, capacity["memory_mib"] - reserve_mib)
        return max(128, min(requested_mib, init_memory_limit_mib, schedulable_mib))

    def _genomescope_hash_size(self, memory_limit_mib: int) -> str:
        if memory_limit_mib >= 4096:
            return "100M"
        if memory_limit_mib >= 2048:
            return "50M"
        return "25M"

    def _detect_effective_cluster_capacity(self, vm_name: Optional[str] = None) -> Dict[str, int]:
        now = time.time()
        if self._resource_cache and now - self._resource_cache[0] < 60:
            return self._capacity_for_vm_partition(dict(self._resource_cache[1]), vm_name)

        capacity = self._detect_total_cluster_capacity()
        self._resource_cache = (now, dict(capacity))
        return self._capacity_for_vm_partition(capacity, vm_name)

    def _detect_total_cluster_capacity(self) -> Dict[str, int]:
        capacity = {"cpu_millis": 1000, "memory_mib": 2048, "storage_mib": 0}
        result = self._run_kubectl(["get", "nodes", "-o", "json"], timeout=30)
        if result.returncode == 0:
            payload = json.loads(result.stdout)
            cpu_millis = 0
            memory_mib = 0
            storage_mib = 0
            for node in payload.get("items", []):
                allocatable = node.get("status", {}).get("allocatable", {})
                cpu_millis += self._parse_cpu_quantity(str(allocatable.get("cpu", "")))
                memory_mib += self._parse_memory_quantity_mib(str(allocatable.get("memory", "")))
                storage_mib += self._parse_memory_quantity_mib(str(allocatable.get("ephemeral-storage", "")))
            if cpu_millis > 0:
                capacity["cpu_millis"] = cpu_millis
            if memory_mib > 0:
                capacity["memory_mib"] = memory_mib
            if storage_mib > 0:
                capacity["storage_mib"] = storage_mib

        docker_capacity = self._detect_minikube_docker_capacity()
        if docker_capacity.get("cpu_millis", 0) > 0:
            capacity["cpu_millis"] = min(capacity["cpu_millis"], docker_capacity["cpu_millis"])
        if docker_capacity.get("memory_mib", 0) > 0:
            capacity["memory_mib"] = min(capacity["memory_mib"], docker_capacity["memory_mib"])

        override_cpu_millis = self._env_int("CASSIE_CLUSTER_CPU_MILLIS")
        override_memory_mib = self._env_int("CASSIE_CLUSTER_MEMORY_MIB")
        override_storage_mib = self._env_int("CASSIE_CLUSTER_STORAGE_MIB")
        if override_cpu_millis > 0:
            capacity["cpu_millis"] = min(capacity["cpu_millis"], override_cpu_millis)
        if override_memory_mib > 0:
            capacity["memory_mib"] = min(capacity["memory_mib"], override_memory_mib)
        if override_storage_mib > 0:
            capacity["storage_mib"] = min(capacity["storage_mib"] or override_storage_mib, override_storage_mib)

        return capacity

    def _capacity_for_vm_partition(self, cluster_capacity: Dict[str, int], vm_name: Optional[str]) -> Dict[str, int]:
        partitions = get_vm_partitions()
        if not partitions:
            return cluster_capacity

        selected_partition = get_vm_partition(vm_name) or partitions[0]
        vm_count = max(1, len(partitions))
        partition_count = max(1, selected_partition.max_jobs)

        cluster_storage_mib = max(0, cluster_capacity.get("storage_mib", 0))
        storage_reserve_mib = min(
            cluster_storage_mib,
            self._env_int("CASSIE_CLUSTER_STORAGE_RESERVE_MIB") or 2048,
        )
        usable_storage_mib = max(0, cluster_storage_mib - storage_reserve_mib)

        vm_cpu_millis = max(0, cluster_capacity["cpu_millis"] // vm_count)
        vm_memory_mib = max(0, cluster_capacity["memory_mib"] // vm_count)
        vm_storage_mib = usable_storage_mib // vm_count if usable_storage_mib > 0 else 0

        partition_capacity = dict(cluster_capacity)
        partition_capacity["vm_count"] = vm_count
        partition_capacity["vm_cpu_millis"] = vm_cpu_millis
        partition_capacity["vm_memory_mib"] = vm_memory_mib
        partition_capacity["vm_storage_mib"] = vm_storage_mib
        partition_capacity["partition_count"] = partition_count
        partition_capacity["cpu_millis"] = max(1, vm_cpu_millis // partition_count)
        partition_capacity["memory_mib"] = max(1, vm_memory_mib // partition_count)

        if usable_storage_mib > 0:
            partition_capacity["storage_mib"] = max(1, vm_storage_mib // partition_count)
        else:
            partition_capacity["storage_mib"] = 0
        return partition_capacity

    def get_vm_capacity_summary(self) -> List[Dict[str, Any]]:
        from backend.api.services.vm_queue_service import get_vm_slot_usage

        total_capacity = self._detect_total_cluster_capacity()
        summaries: List[Dict[str, Any]] = []

        for partition in get_vm_partitions():
            capacity = self._capacity_for_vm_partition(total_capacity, partition.name)
            slot_usage = get_vm_slot_usage(partition.name)
            summaries.append(
                {
                    "name": partition.name,
                    "display_name": partition.display_name,
                    "max_jobs": partition.max_jobs,
                    "max_pods": partition.max_jobs,
                    "running_jobs": slot_usage["running_jobs"],
                    "active_jobs": slot_usage.get("active_jobs", slot_usage["running_jobs"]),
                    "available_job_slots": slot_usage["available_job_slots"],
                    "vm_count": capacity.get("vm_count", len(get_vm_partitions())),
                    "partition_count": capacity.get("partition_count", partition.max_jobs),
                    "vm_cpu_millis": capacity.get("vm_cpu_millis", 0),
                    "vm_memory_mib": capacity.get("vm_memory_mib", 0),
                    "vm_storage_mib": capacity.get("vm_storage_mib", 0),
                    "available_cpu_millis": capacity["cpu_millis"],
                    "available_memory_mib": capacity["memory_mib"],
                    "available_storage_mib": capacity.get("storage_mib", 0),
                }
            )

        return summaries

    def _detect_minikube_docker_capacity(self) -> Dict[str, int]:
        if not shutil.which("docker"):
            return {}

        try:
            result = subprocess.run(
                ["docker", "inspect", "minikube", "--format", "{{.HostConfig.Memory}} {{.HostConfig.NanoCpus}}"],
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except Exception:
            return {}

        if result.returncode != 0:
            return {}

        parts = result.stdout.strip().split()
        if len(parts) != 2:
            return {}

        memory_bytes = int(parts[0]) if parts[0].isdigit() else 0
        nano_cpus = int(parts[1]) if parts[1].isdigit() else 0
        detected: Dict[str, int] = {}
        if memory_bytes > 0:
            detected["memory_mib"] = max(1, memory_bytes // (1024 * 1024))
        if nano_cpus > 0:
            detected["cpu_millis"] = max(1, nano_cpus // 1_000_000)
        return detected

    def _env_bool_or_none(self, env_name: str) -> Optional[bool]:
        raw_value = os.getenv(env_name)
        if raw_value is None:
            return None
        normalized = raw_value.strip().lower()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        return None

    def _env_value_or_default(self, env_name: str, default: str) -> str:
        raw_value = os.getenv(env_name)
        if raw_value is None:
            return default
        value = raw_value.strip()
        if not value or value.lower() == "auto":
            return default
        return value

    def _env_int(self, env_name: str) -> int:
        raw_value = os.getenv(env_name, "").strip()
        if not raw_value:
            return 0
        try:
            return max(0, int(raw_value))
        except ValueError:
            return 0

    def _parse_cpu_quantity(self, quantity: str) -> int:
        value = quantity.strip()
        if not value:
            return 0
        if value.endswith("m"):
            return int(float(value[:-1]))
        return int(float(value) * 1000)

    def _parse_memory_quantity_mib(self, quantity: str) -> int:
        value = quantity.strip()
        if not value:
            return 0
        units = {
            "Ki": 1 / 1024,
            "Mi": 1,
            "Gi": 1024,
            "Ti": 1024 * 1024,
            "K": 1000 / (1024 * 1024),
            "M": 1000 * 1000 / (1024 * 1024),
            "G": 1000 * 1000 * 1000 / (1024 * 1024),
        }
        for suffix, multiplier in units.items():
            if value.endswith(suffix):
                return int(float(value[: -len(suffix)]) * multiplier)
        return int(float(value) / (1024 * 1024))

    def _format_cpu_quantity(self, cpu_millis: int) -> str:
        if cpu_millis >= 1000 and cpu_millis % 1000 == 0:
            return str(cpu_millis // 1000)
        return f"{cpu_millis}m"

    def _artifact_formats(self, artifact: Dict[str, Any]) -> set[str]:
        formats: set[str] = set()
        declared_format = str(artifact.get("file_format") or "").strip().lower().lstrip(".")
        if declared_format:
            formats.add(declared_format)

        filename = str(artifact.get("filename") or "").lower()
        if filename.endswith((".fastq", ".fq", ".fastq.gz", ".fq.gz")):
            formats.add("fastq")
        if filename.endswith((".fasta", ".fa", ".fna", ".fasta.gz", ".fa.gz", ".fna.gz")):
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
        if filename.endswith((".meryl", ".meryl.tar", ".meryl.tar.gz", ".meryl.tgz")):
            formats.add("meryl")
        if filename.endswith((".txt", ".cfg", ".conf", ".ini", ".json")):
            formats.add("txt")
        if filename.endswith(".json"):
            formats.add("json")
        return formats

    def _classify_inputs(self, current_inputs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        fastq: List[Dict[str, Any]] = []
        fasta: List[Dict[str, Any]] = []
        reads_like: List[Dict[str, Any]] = []
        annotation: List[Dict[str, Any]] = []
        hal: List[Dict[str, Any]] = []
        meryl: List[Dict[str, Any]] = []
        text: List[Dict[str, Any]] = []

        for artifact in current_inputs:
            formats = self._artifact_formats(artifact)
            if "fastq" in formats:
                fastq.append(artifact)
                reads_like.append(artifact)
            if "fasta" in formats:
                fasta.append(artifact)
                reads_like.append(artifact)
            if formats.intersection({"gff", "gff3", "gtf"}):
                annotation.append(artifact)
            if "hal" in formats:
                hal.append(artifact)
            if "meryl" in formats:
                meryl.append(artifact)
            if formats.intersection({"txt", "json", "cfg", "conf", "ini"}):
                text.append(artifact)

        fastq.sort(key=lambda item: item["filename"].lower())
        fasta.sort(key=lambda item: item["filename"].lower())
        reads_like.sort(key=lambda item: item["filename"].lower())
        annotation.sort(key=lambda item: item["filename"].lower())
        hal.sort(key=lambda item: item["filename"].lower())
        meryl.sort(key=lambda item: item["filename"].lower())
        text.sort(key=lambda item: item["filename"].lower())

        return {
            "fastq": fastq,
            "fasta": fasta,
            "reads_like": reads_like,
            "annotation": annotation,
            "hal": hal,
            "meryl": meryl,
            "text": text,
        }

    def _resolve_quast_inputs(self, fasta_files: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if len(fasta_files) < 2:
            raise ValueError("QUAST requires an assembly FASTA and a reference FASTA")

        assembly = None
        reference = None

        for artifact in fasta_files:
            filename = artifact["filename"].lower()
            if self._is_assembly_artifact(artifact) or any(
                token in filename for token in ("contig", "scaffold", "assembly")
            ):
                assembly = artifact
                break

        if assembly is None:
            assembly = fasta_files[0]

        for artifact in fasta_files:
            if artifact["filename"] != assembly["filename"]:
                reference = artifact
                break

        if reference is None:
            raise ValueError("Could not determine reference FASTA for QUAST")

        return assembly, reference

    def _select_fastq_inputs(self, fastq_files: List[Dict[str, Any]], required: int = 2) -> List[Dict[str, Any]]:
        """Prefer R1/R2 style ordering when filenames include pair hints."""
        if len(fastq_files) <= 1:
            return fastq_files

        def score(item: Dict[str, Any]) -> Tuple[int, str]:
            name = item["filename"].lower()
            if any(token in name for token in ("_r1", ".r1", "-r1", "_1.", ".1.", "-1.")):
                return (0, name)
            if any(token in name for token in ("_r2", ".r2", "-r2", "_2.", ".2.", "-2.")):
                return (1, name)
            return (2, name)

        ordered = sorted(fastq_files, key=score)
        return ordered[:required]

    def _make_job_name(self, job_id: int, execution_id: int, stage_number: int, tool_id: str) -> str:
        safe_tool = re.sub(r"[^a-z0-9-]", "-", tool_id.lower())
        return f"cassie-j{job_id}-e{execution_id}-s{stage_number}-{safe_tool}"[:63].rstrip("-")

    def _wait_for_stage_container(self, job_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        timeout_seconds = self._config.kubernetes.job_timeout_seconds
        poll_interval = max(1, self._config.kubernetes.poll_interval_seconds)
        deadline = time.time() + timeout_seconds if timeout_seconds > 0 else None

        pod_name = ""

        while deadline is None or time.time() < deadline:
            pod_name = self._get_job_pod_name(job_name)
            if pod_name:
                pod_result = self._run_kubectl(
                    ["get", "pod", pod_name, "-n", namespace, "-o", "json"],
                    timeout=60,
                )
                if pod_result.returncode != 0:
                    if "timed out" in (pod_result.stderr or "").lower():
                        time.sleep(poll_interval)
                        continue
                    raise RuntimeError(
                        f"Failed to fetch Kubernetes pod status for {pod_name}: {pod_result.stderr.strip()}"
                    )

                pod_payload = json.loads(pod_result.stdout)
                pod_status = pod_payload.get("status", {}) or {}
                if pod_status.get("phase") == "Failed":
                    reason = str(pod_status.get("reason") or "").strip()
                    message = str(pod_status.get("message") or "").strip()
                    logs = self._get_stage_failure_logs(job_name)
                    details = " ".join(part for part in (reason, message, logs[-2000:] if logs else "") if part)
                    raise RuntimeError(
                        f"Kubernetes Job {job_name} failed. {details or 'The pod entered Failed phase.'}"
                    )

                init_container_statuses = pod_payload.get("status", {}).get("initContainerStatuses", []) or []
                for init_status in init_container_statuses:
                    init_name = init_status.get("name", "init")
                    waiting = (init_status.get("state") or {}).get("waiting")
                    if waiting:
                        reason = waiting.get("reason", "")
                        message = waiting.get("message", "").strip()
                        fatal_waiting_reasons = {
                            "ErrImagePull",
                            "ImagePullBackOff",
                            "InvalidImageName",
                            "CreateContainerConfigError",
                            "CreateContainerError",
                            "RunContainerError",
                            "CrashLoopBackOff",
                        }
                        if reason in fatal_waiting_reasons:
                            details = f"{reason}: {message}" if message else reason
                            logs = self._get_pod_container_logs(pod_name, init_name)
                            raise RuntimeError(
                                f"Kubernetes Job {job_name} init container {init_name} is blocked. "
                                f"{details}\n{logs[-4000:] if logs else 'No logs captured.'}"
                            )

                    terminated = (init_status.get("state") or {}).get("terminated")
                    if terminated:
                        exit_code = int(terminated.get("exitCode", 1))
                        if exit_code != 0:
                            reason = terminated.get("reason", "")
                            logs = self._get_pod_container_logs(pod_name, init_name)
                            raise RuntimeError(
                                f"Kubernetes Job {job_name} init container {init_name} failed "
                                f"with exit code {exit_code}{f' ({reason})' if reason else ''}.\n"
                                f"{logs[-4000:] if logs else 'No logs captured.'}"
                            )

                container_statuses = pod_payload.get("status", {}).get("containerStatuses", []) or []
                tool_status = next(
                    (status for status in container_statuses if status.get("name") == "tool"),
                    None,
                )
                if tool_status:
                    waiting = (tool_status.get("state") or {}).get("waiting")
                    if waiting:
                        reason = waiting.get("reason", "")
                        message = waiting.get("message", "").strip()
                        fatal_waiting_reasons = {
                            "ErrImagePull",
                            "ImagePullBackOff",
                            "InvalidImageName",
                            "CreateContainerConfigError",
                            "CreateContainerError",
                            "RunContainerError",
                            "CrashLoopBackOff",
                        }
                        if reason in fatal_waiting_reasons:
                            details = f"{reason}: {message}" if message else reason
                            raise RuntimeError(
                                f"Kubernetes Job {job_name} is blocked before start. {details}"
                            )
                    terminated = (tool_status.get("state") or {}).get("terminated")
                    if terminated:
                        exit_code = int(terminated.get("exitCode", 1))
                        if exit_code == 0:
                            return pod_name
                        logs = self._get_job_logs(job_name)
                        raise RuntimeError(
                            f"Kubernetes Job {job_name} failed with exit code {exit_code}.\n"
                            f"{logs[-4000:] if logs else 'No logs captured.'}"
                        )

            status_result = self._run_kubectl(
                ["get", "job", job_name, "-n", namespace, "-o", "json"],
                timeout=60,
            )
            if status_result.returncode != 0:
                if "timed out" in (status_result.stderr or "").lower():
                    time.sleep(poll_interval)
                    continue
                raise RuntimeError(f"Failed to fetch Kubernetes Job status for {job_name}: {status_result.stderr.strip()}")

            payload = json.loads(status_result.stdout)
            status = payload.get("status", {})
            if status.get("failed", 0) >= 1:
                logs = self._get_stage_failure_logs(job_name)
                raise RuntimeError(
                    f"Kubernetes Job {job_name} failed.\n{logs[-4000:] if logs else 'No logs captured.'}"
                )

            time.sleep(poll_interval)

        if timeout_seconds > 0:
            raise TimeoutError(f"Kubernetes Job {job_name} exceeded timeout of {timeout_seconds} seconds")

        raise RuntimeError(f"Kubernetes Job {job_name} stopped waiting unexpectedly without a timeout configuration")

    def _get_job_pod_name(self, job_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        result = self._run_kubectl(
            ["get", "pods", "-n", namespace, "-l", f"job-name={job_name}", "-o", "json"],
            timeout=60,
        )
        if result.returncode != 0:
            return ""
        payload = json.loads(result.stdout)
        items = payload.get("items", [])
        if not items:
            return ""
        return items[0]["metadata"]["name"]

    def _copy_job_outputs(self, namespace: str, pod_name: str, tool_id: str, job_name: str) -> str:
        if not pod_name:
            raise RuntimeError(f"Could not determine pod name for completed Kubernetes Job {job_name}")

        temp_dir = tempfile.mkdtemp(prefix=f"cassie_k8s_{tool_id.lower()}_")
        destination = Path(temp_dir) / "output"
        destination.mkdir(parents=True, exist_ok=True)
        copy_error = self._stream_copy_job_outputs(namespace, pod_name, destination, timeout=180)
        if copy_error:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to copy outputs from pod {pod_name}: {copy_error}")
        return str(destination)

    def _stream_copy_job_outputs(
        self,
        namespace: str,
        pod_name: str,
        destination: Path,
        timeout: int = 180,
    ) -> str:
        cmd = [
            "kubectl",
            "exec",
            "-n",
            namespace,
            "-c",
            "artifacts",
            pod_name,
            "--",
            "tar",
            "cf",
            "-",
            "-C",
            "/workspace/output",
            ".",
        ]
        self._logger.info("Running kubectl command: %s", " ".join(cmd))

        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            cwd=str(destination.parent),
            env=_kubectl_env(),
        )
        try:
            assert process.stdout is not None
            with tarfile.open(fileobj=process.stdout, mode="r|*") as tar:
                for member in tar:
                    member_name = member.name or ""
                    resolved_target = (destination / member_name).resolve()
                    try:
                        resolved_target.relative_to(destination.resolve())
                    except ValueError:
                        process.kill()
                        process.communicate()
                        return f"Refused to extract unsafe archive path: {member_name}"
                    tar.extract(member, path=destination, filter="data")
            _, stderr = process.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            process.kill()
            _, stderr = process.communicate()
            return (stderr or b"").decode("utf-8", errors="replace").strip() or "timed out while streaming outputs"
        except tarfile.TarError as exc:
            process.kill()
            _, stderr = process.communicate()
            stderr_text = (stderr or b"").decode("utf-8", errors="replace").strip()
            return stderr_text or str(exc)

        if process.returncode != 0:
            return (stderr or b"").decode("utf-8", errors="replace").strip() or f"kubectl exec exited with code {process.returncode}"

        return ""

    def _read_stage_resource_usage(self, local_output_dir: str) -> Dict[str, Any]:
        usage_path = Path(local_output_dir) / ".cassie_resource_usage.json"
        if not usage_path.exists():
            return {}

        try:
            payload = json.loads(usage_path.read_text(encoding="utf-8"))
            cpu_usage_seconds = float(payload.get("cpu_usage_seconds") or 0)
            wall_time_seconds = float(payload.get("wall_time_seconds") or 0)
            if cpu_usage_seconds <= 0:
                return {}
            return {
                "measured_cpu_core_seconds": round(cpu_usage_seconds, 6),
                "measured_wall_time_seconds": round(max(0.0, wall_time_seconds), 6),
                "resource_usage_source": str(payload.get("source") or "container_cgroup_cpu_stat"),
            }
        except Exception as exc:
            self._logger.warning("Could not read stage resource usage from %s: %s", usage_path, exc)
            return {}

    def _upload_stage_outputs(
        self,
        local_output_dir: str,
        job_id: int,
        execution_id: int,
        user_id: int,
        stage_number: int,
        tool: Dict[str, Any],
        current_inputs: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not os.path.isdir(local_output_dir):
            raise RuntimeError(f"Expected output directory does not exist: {local_output_dir}")

        minio_client = get_minio_client()
        stage_outputs: List[Dict[str, Any]] = []

        try:
            for root, _, files in os.walk(local_output_dir):
                for filename in files:
                    if filename == ".cassie_resource_usage.json":
                        continue
                    local_path = os.path.join(root, filename)
                    rel_path = os.path.relpath(local_path, local_output_dir).replace("\\", "/")
                    safe_filename = self._stage_output_display_name(tool, rel_path, current_inputs)
                    s3_key = (
                        f"jobs/{job_id}/executions/{execution_id}/"
                        f"stage_{stage_number:02d}_{tool['id'].lower()}/{rel_path}"
                    )

                    upload_result = minio_client.upload_file(
                        user_id=user_id,
                        local_path=local_path,
                        s3_key=s3_key,
                    )

                    create_file_record(
                        FileCreate(
                            job_id=job_id,
                            filename=safe_filename,
                            s3_key=s3_key,
                            file_type=FileType.OUTPUT,
                            file_format=self._infer_output_file_format(filename),
                            size_bytes=upload_result["size"],
                            checksum=upload_result["checksum"],
                        )
                    )

                    stage_outputs.append(
                        {
                            "filename": safe_filename,
                            "s3_key": s3_key,
                            "size_bytes": upload_result["size"],
                            "file_format": self._infer_output_file_format(filename),
                            "source": "stage-output",
                            "producer_tool_id": tool["id"],
                        }
                    )
        finally:
            shutil.rmtree(Path(local_output_dir).parent, ignore_errors=True)

        return stage_outputs

    def _upload_stage_log_artifacts(
        self,
        *,
        stage_info: Dict[str, Any],
        job_id: int,
        execution_id: int,
        user_id: int,
        stage_number: int,
        tool: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        if stage_info.get("_log_artifacts_uploaded"):
            return list(stage_info.get("log_artifacts") or [])

        minio_client = get_minio_client()
        log_artifacts: List[Dict[str, Any]] = []
        tool_slug = self._tool_output_slug(tool)
        stage_prefix = f"stage_{stage_number:02d}_{tool_slug}"
        log_sources = (
            ("tool_logs_full", f"{stage_prefix}__tool.txt"),
        )

        temp_dir = Path(tempfile.mkdtemp(prefix=f"cassie-stage-logs-{job_id}-{stage_number:02d}-"))
        try:
            for source_key, artifact_name in log_sources:
                log_content = str(stage_info.get(source_key) or "").strip()
                if not log_content:
                    continue

                local_path = temp_dir / artifact_name
                local_path.write_text(log_content + "\n", encoding="utf-8")
                s3_key = f"jobs/{job_id}/executions/{execution_id}/{artifact_name}"
                upload_result = minio_client.upload_file(
                    user_id=user_id,
                    local_path=str(local_path),
                    s3_key=s3_key,
                )
                create_file_record(
                    FileCreate(
                        job_id=job_id,
                        filename=artifact_name,
                        s3_key=s3_key,
                        file_type=FileType.LOG,
                        file_format="txt",
                        size_bytes=upload_result["size"],
                        checksum=upload_result["checksum"],
                    )
                )
                log_artifacts.append(
                    {
                        "filename": artifact_name,
                        "s3_key": s3_key,
                        "size_bytes": upload_result["size"],
                        "file_format": "txt",
                        "source": source_key,
                        "producer_tool_id": tool["id"],
                    }
                )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

        stage_info["_log_artifacts_uploaded"] = True
        if log_artifacts:
            stage_info["log_artifacts"] = log_artifacts
        return log_artifacts

    def _stage_output_display_name(
        self,
        tool: Dict[str, Any],
        rel_path: str,
        current_inputs: List[Dict[str, Any]],
    ) -> str:
        normalized_rel = rel_path.replace("\\", "/").strip("/")
        path_parts = [part for part in normalized_rel.split("/") if part and part != "."]
        if not path_parts:
            return "output.dat"

        tool_slug = self._tool_output_slug(tool)
        filename = path_parts[-1]
        parent_parts = [
            self._apply_input_aliases(self._normalize_output_segment(part), current_inputs)
            for part in path_parts[:-1]
        ]
        parent_parts = [
            part for part in parent_parts
            if part and part not in {"output", f"{tool_slug}_out", tool_slug}
        ][-2:]

        file_label = self._normalize_output_filename(tool_slug, filename, current_inputs)
        display_name = "__".join(part for part in [tool_slug, *parent_parts, file_label] if part)

        if len(display_name) > 120:
            display_name = self._shorten_filename_preserving_suffixes(display_name, max_length=120)

        return display_name

    def _tool_output_slug(self, tool: Dict[str, Any]) -> str:
        return self._normalize_output_segment(str(tool.get("id") or tool.get("name") or "output")) or "output"

    def _normalize_output_filename(self, tool_slug: str, filename: str, current_inputs: List[Dict[str, Any]]) -> str:
        base_name, suffix = self._split_filename_suffix(filename)
        normalized_base = self._normalize_output_segment(base_name) or "output"
        normalized_base = self._apply_input_aliases(normalized_base, current_inputs)

        if tool_slug == "fastqc" and normalized_base.lower().endswith("_fastqc"):
            normalized_base = normalized_base[:-7].rstrip("._-") or "report"

        if normalized_base.lower().startswith(f"{tool_slug}_"):
            normalized_base = normalized_base[len(tool_slug) + 1:] or normalized_base

        normalized_base = self._shorten_middle(normalized_base, 56)
        return f"{normalized_base}{suffix}"

    def _normalize_output_segment(self, value: str) -> str:
        return re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip()).strip("._-").lower()

    def _apply_input_aliases(self, value: str, current_inputs: List[Dict[str, Any]]) -> str:
        normalized_value = value.strip().lower()
        if not normalized_value:
            return normalized_value

        for input_stem, alias in self._input_display_aliases(current_inputs):
            if normalized_value == input_stem:
                return alias
            normalized_value = re.sub(
                rf"(^|[_\-.]){re.escape(input_stem)}(?=$|[_\-.])",
                lambda match: f"{match.group(1)}{alias}",
                normalized_value,
            )

        normalized_value = re.sub(r"__+", "_", normalized_value).strip("._-")
        return normalized_value or value

    def _input_display_aliases(self, current_inputs: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        aliases: List[Tuple[str, str]] = []
        seen_stems: set[str] = set()
        read_index = 0
        ref_index = 0
        input_index = 0

        for artifact in current_inputs:
            filename = os.path.basename(str(artifact.get("filename", "") or ""))
            if not filename:
                continue

            stem, _ = self._split_filename_suffix(filename)
            normalized_stem = self._normalize_output_segment(stem)
            if not normalized_stem or normalized_stem in seen_stems:
                continue

            lowered = filename.lower()
            if lowered.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq")):
                read_index += 1
                alias = f"read{read_index:02d}"
            elif lowered.endswith((".fasta.gz", ".fa.gz", ".fna.gz", ".fasta", ".fa", ".fna")):
                ref_index += 1
                alias = f"ref{ref_index:02d}"
            else:
                input_index += 1
                alias = f"input{input_index:02d}"

            seen_stems.add(normalized_stem)
            aliases.append((normalized_stem, alias))

        aliases.sort(key=lambda item: len(item[0]), reverse=True)
        return aliases

    def _split_filename_suffix(self, filename: str) -> Tuple[str, str]:
        lower_name = filename.lower()
        for compound_suffix in (".fastq.gz", ".fq.gz", ".fasta.gz", ".fa.gz", ".fna.gz", ".tar.gz"):
            if lower_name.endswith(compound_suffix):
                return filename[: -len(compound_suffix)], filename[-len(compound_suffix):]

        path = Path(filename)
        suffix = "".join(path.suffixes)
        if suffix:
            return filename[: -len(suffix)], suffix
        return filename, ""

    def _shorten_middle(self, value: str, max_length: int) -> str:
        if len(value) <= max_length:
            return value

        keep_left = max(8, (max_length - 3) // 2)
        keep_right = max(8, max_length - 3 - keep_left)
        return f"{value[:keep_left]}...{value[-keep_right:]}"

    def _shorten_filename_preserving_suffixes(self, filename: str, max_length: int) -> str:
        if len(filename) <= max_length:
            return filename

        base_name, suffix = self._split_filename_suffix(filename)
        max_base_length = max(12, max_length - len(suffix))
        shortened_base = self._shorten_middle(base_name, max_base_length)
        return f"{shortened_base}{suffix}"

    def _infer_output_file_format(self, filename: str) -> str:
        lower_name = filename.lower()
        if lower_name.endswith((".fastq.gz", ".fq.gz", ".fastq", ".fq")):
            return "fastq"
        if lower_name.endswith((".fasta.gz", ".fa.gz", ".fna.gz", ".fasta", ".fa", ".fna")):
            return "fasta"
        if lower_name.endswith(".gff3"):
            return "gff3"
        if lower_name.endswith(".gff"):
            return "gff"
        if lower_name.endswith(".gtf"):
            return "gtf"
        if lower_name.endswith(".hal"):
            return "hal"
        if lower_name.endswith(".gfa"):
            return "gfa"
        if lower_name.endswith((".meryl", ".meryl.tar", ".meryl.tar.gz", ".meryl.tgz")):
            return "meryl"
        if lower_name.endswith(".txt"):
            return "txt"
        if lower_name.endswith(".json"):
            return "json"
        if lower_name.endswith(".html"):
            return "html"
        if lower_name.endswith(".tsv"):
            return "tsv"
        if lower_name.endswith(".csv"):
            return "csv"
        if lower_name.endswith(".zip"):
            return "zip"
        if lower_name.endswith(".pdf"):
            return "pdf"
        suffix = Path(filename).suffix.lstrip(".")
        return suffix or "dat"

    def _get_job_logs(self, job_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        result = self._run_kubectl(["logs", f"job/{job_name}", "-n", namespace, "-c", "tool"], timeout=60)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if self._is_transient_log_unavailable(stderr):
                return ""
            return stderr
        return result.stdout

    def _get_pod_container_logs(self, pod_name: str, container_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        result = self._run_kubectl(["logs", pod_name, "-n", namespace, "-c", container_name], timeout=60)
        if result.returncode != 0:
            stderr = result.stderr.strip()
            if self._is_transient_log_unavailable(stderr):
                return ""
            return stderr
        return result.stdout

    def _is_transient_log_unavailable(self, message: str) -> bool:
        normalized = str(message or "").strip().lower()
        if not normalized:
            return True
        return any(
            marker in normalized
            for marker in (
                "podinitializing",
                "containercreating",
                "waiting to start",
                "is waiting to start",
                "no such container",
            )
        )

    def _get_stage_failure_logs(self, job_name: str) -> str:
        pod_name = self._get_job_pod_name(job_name)
        if not pod_name:
            return self._get_job_logs(job_name)

        namespace = self._config.kubernetes.namespace
        pod_result = self._run_kubectl(["get", "pod", pod_name, "-n", namespace, "-o", "json"], timeout=60)
        if pod_result.returncode != 0:
            return pod_result.stderr.strip()

        pod_payload = json.loads(pod_result.stdout)
        for status in pod_payload.get("status", {}).get("initContainerStatuses", []) or []:
            terminated = (status.get("state") or {}).get("terminated")
            waiting = (status.get("state") or {}).get("waiting")
            if terminated or waiting:
                return self._get_pod_container_logs(pod_name, status.get("name", "fetch-inputs"))

        return self._get_job_logs(job_name)

    def _capture_stage_logs(
        self,
        stage_info: Dict[str, Any],
        job_name: str,
        *,
        pod_name: Optional[str] = None,
    ) -> None:
        """Persist full stage logs into stage metadata for later admin inspection."""
        resolved_pod_name = pod_name or str(stage_info.get("pod_name") or "").strip() or self._get_job_pod_name(job_name)
        if resolved_pod_name:
            stage_info["pod_name"] = resolved_pod_name
            init_logs = self._get_pod_container_logs(resolved_pod_name, "fetch-inputs")
            if init_logs and "not found" not in init_logs.lower():
                stage_info["init_logs_full"] = init_logs
            tool_logs = self._get_pod_container_logs(resolved_pod_name, "tool")
            if tool_logs and "not found" not in tool_logs.lower():
                stage_info["tool_logs_full"] = tool_logs
                stage_info["logs_preview"] = tool_logs[-2000:]
            return

        tool_logs = self._get_job_logs(job_name)
        if tool_logs and "not found" not in tool_logs.lower():
            stage_info["tool_logs_full"] = tool_logs
            stage_info["logs_preview"] = tool_logs[-2000:]

    def _cluster_visible_minio_endpoint(self, endpoint: str) -> str:
        override = self._config.kubernetes.minio_endpoint.strip()
        if override:
            return override

        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        if host in {"127.0.0.1", "localhost"}:
            replacement_host = os.getenv("CASSIE_HOST_IP", "").strip() or "host.docker.internal"
            netloc = parsed.netloc.replace(host, replacement_host)
            parsed = parsed._replace(netloc=netloc)
        return urlunparse(parsed)

    def _persist_execution_state(
        self,
        execution_id: int,
        parameters_used: Dict[str, Any],
        tool_versions: Optional[Dict[str, str]] = None,
    ) -> None:
        update_job_execution(
            execution_id,
            JobExecutionUpdate(
                parameters_used=parameters_used,
                tool_versions=tool_versions,
            ),
        )

    def resume_execution_from_checkpoint(self, job_id: int, user_id: int) -> Dict[str, Any]:
        """Release all currently waiting checkpoints for the latest running execution."""
        executions = get_running_executions()
        target_execution = next((execution for execution in executions if execution.job_id == job_id), None)
        if target_execution is None:
            raise ValueError("No running execution is waiting on a checkpoint for this job.")

        parameters_used = getattr(target_execution, "parameters_used", None) or {}
        stages = parameters_used.get("stages") if isinstance(parameters_used, dict) else None
        if not isinstance(stages, list):
            raise ValueError("This job has no checkpoint state to resume.")

        waiting_checkpoint_ids = [
            str(stage.get("stage_id") or "").strip()
            for stage in stages
            if isinstance(stage, dict) and str(stage.get("status") or "").strip().lower() == "waiting_for_checkpoint"
        ]
        waiting_checkpoint_ids = [stage_id for stage_id in waiting_checkpoint_ids if stage_id]
        if not waiting_checkpoint_ids:
            raise ValueError("This job is not currently waiting on any checkpoint.")

        release_bucket = self._checkpoint_releases.get(target_execution.id)
        resume_event = self._checkpoint_events.get(target_execution.id)
        event_loop = self._execution_loops.get(target_execution.id)
        if release_bucket is None or resume_event is None or event_loop is None:
            raise RuntimeError("Checkpoint state is not available in the active backend process. Please retry the job.")

        for stage in stages:
            if not isinstance(stage, dict):
                continue
            if str(stage.get("stage_id") or "").strip() not in waiting_checkpoint_ids:
                continue
            stage["status"] = "pending"
            stage["resume_requested_at"] = datetime.now().isoformat()

        update_job_execution(
            target_execution.id,
            JobExecutionUpdate(parameters_used=parameters_used),
        )

        def _release() -> None:
            release_bucket.update(waiting_checkpoint_ids)
            resume_event.set()

        event_loop.call_soon_threadsafe(_release)
        return {
            "execution_id": target_execution.id,
            "released_checkpoints": waiting_checkpoint_ids,
        }

    def _terminate_stage_job(self, stage_job_name: str) -> None:
        namespace = self._config.kubernetes.namespace
        self._run_kubectl(
            ["delete", "job", stage_job_name, "-n", namespace, "--ignore-not-found=true", "--cascade=foreground"],
            timeout=60,
        )

    def terminate_job_stages(self, job_id: int, executions: List[Any]) -> Dict[str, Any]:
        """Delete active Kubernetes stage Jobs/Pods for a CASSIE job."""
        namespace = self._config.kubernetes.namespace
        deleted_stage_jobs: List[str] = []
        errors: List[str] = []
        seen_stage_jobs: set[str] = set()

        for execution in executions:
            parameters_used = getattr(execution, "parameters_used", None) or {}
            stages = parameters_used.get("stages") if isinstance(parameters_used, dict) else None
            if not isinstance(stages, list):
                continue

            for stage in stages:
                if not isinstance(stage, dict):
                    continue
                stage_job_name = str(stage.get("kubernetes_job_name") or "").strip()
                if not stage_job_name or stage_job_name in seen_stage_jobs:
                    continue
                seen_stage_jobs.add(stage_job_name)

                delete_result = self._run_kubectl(
                    ["delete", "job", stage_job_name, "-n", namespace, "--ignore-not-found=true", "--cascade=foreground"],
                    timeout=60,
                )
                if delete_result.returncode == 0:
                    deleted_stage_jobs.append(stage_job_name)
                else:
                    errors.append(f"{stage_job_name}: {delete_result.stderr.strip() or delete_result.stdout.strip() or 'unknown kubectl delete failure'}")

        label_selector = f"cassie/job-id={job_id}"
        pod_delete_result = self._run_kubectl(
            ["delete", "pod", "-n", namespace, "-l", label_selector, "--ignore-not-found=true", "--force", "--grace-period=0"],
            timeout=60,
        )
        if pod_delete_result.returncode != 0:
            errors.append(
                f"pods for {label_selector}: {pod_delete_result.stderr.strip() or pod_delete_result.stdout.strip() or 'unknown kubectl pod delete failure'}"
            )

        return {
            "namespace": namespace,
            "deleted_stage_jobs": deleted_stage_jobs,
            "errors": errors,
        }

    def get_job_runtime_details(self, job_id: int, executions: List[Any]) -> Dict[str, Any]:
        """Return live Kubernetes status and recent log snippets for admin inspection."""
        namespace = self._config.kubernetes.namespace
        stages: List[Dict[str, Any]] = []
        errors: List[str] = []

        for execution in executions:
            parameters_used = getattr(execution, "parameters_used", None) or {}
            stage_entries = parameters_used.get("stages") if isinstance(parameters_used, dict) else None
            if not isinstance(stage_entries, list):
                continue

            for stage in stage_entries:
                if not isinstance(stage, dict):
                    continue

                stage_job_name = str(stage.get("kubernetes_job_name") or "").strip()
                pod_name = str(stage.get("pod_name") or "").strip()
                snapshot: Dict[str, Any] = {
                    "job_id": job_id,
                    "execution_id": getattr(execution, "id", None),
                    "execution_number": getattr(execution, "execution_number", None),
                    "stage_number": stage.get("stage_number"),
                    "tool_id": stage.get("tool_id"),
                    "tool_name": stage.get("tool_name"),
                    "recorded_status": stage.get("status"),
                    "recorded_error": stage.get("error"),
                    "kubernetes_job_name": stage_job_name or None,
                    "pod_name": pod_name or None,
                    "job_status": None,
                    "pod_phase": None,
                    "live_init_logs": None,
                    "live_tool_logs": None,
                    "raw_job_status": None,
                    "raw_pod_status": None,
                }

                if stage_job_name:
                    job_result = self._run_kubectl(
                        ["get", "job", stage_job_name, "-n", namespace, "-o", "json"],
                        timeout=60,
                    )
                    if job_result.returncode == 0:
                        try:
                            job_payload = json.loads(job_result.stdout)
                            status_payload = job_payload.get("status", {}) or {}
                            snapshot["raw_job_status"] = status_payload
                            conditions = status_payload.get("conditions", []) or []
                            if conditions:
                                latest_condition = conditions[-1]
                                snapshot["job_status"] = latest_condition.get("type") or "Unknown"
                            elif status_payload.get("active", 0):
                                snapshot["job_status"] = "Active"
                            elif status_payload.get("succeeded", 0):
                                snapshot["job_status"] = "Succeeded"
                            elif status_payload.get("failed", 0):
                                snapshot["job_status"] = "Failed"
                        except json.JSONDecodeError as exc:
                            errors.append(f"{stage_job_name}: could not parse Kubernetes job payload ({exc})")
                    else:
                        stderr = (job_result.stderr or job_result.stdout or "").strip()
                        if stderr and "NotFound" not in stderr:
                            errors.append(f"{stage_job_name}: {stderr}")

                if not pod_name and stage_job_name:
                    pod_name = self._get_job_pod_name(stage_job_name)
                    snapshot["pod_name"] = pod_name or None

                if pod_name:
                    pod_result = self._run_kubectl(
                        ["get", "pod", pod_name, "-n", namespace, "-o", "json"],
                        timeout=60,
                    )
                    if pod_result.returncode == 0:
                        try:
                            pod_payload = json.loads(pod_result.stdout)
                            status_payload = pod_payload.get("status", {}) or {}
                            snapshot["raw_pod_status"] = status_payload
                            snapshot["pod_phase"] = status_payload.get("phase")
                        except json.JSONDecodeError as exc:
                            errors.append(f"{pod_name}: could not parse Kubernetes pod payload ({exc})")
                    else:
                        stderr = (pod_result.stderr or pod_result.stdout or "").strip()
                        if stderr and "NotFound" not in stderr:
                            errors.append(f"{pod_name}: {stderr}")

                    init_logs = self._run_kubectl(
                        ["logs", pod_name, "-n", namespace, "-c", "fetch-inputs", "--tail=120"],
                        timeout=60,
                    )
                    if init_logs.returncode == 0 and init_logs.stdout.strip():
                        snapshot["live_init_logs"] = init_logs.stdout[-8000:]

                    tool_logs = self._run_kubectl(
                        ["logs", pod_name, "-n", namespace, "-c", "tool", "--tail=200"],
                        timeout=60,
                    )
                    if tool_logs.returncode == 0 and tool_logs.stdout.strip():
                        snapshot["live_tool_logs"] = tool_logs.stdout[-12000:]
                elif stage_job_name:
                    job_logs = self._run_kubectl(
                        ["logs", f"job/{stage_job_name}", "-n", namespace, "-c", "tool", "--tail=200"],
                        timeout=60,
                    )
                    if job_logs.returncode == 0 and job_logs.stdout.strip():
                        snapshot["live_tool_logs"] = job_logs.stdout[-12000:]

                stages.append(snapshot)

        return {
            "namespace": namespace,
            "stages": stages,
            "errors": errors,
        }

    def recover_orphaned_executions(self) -> Dict[str, Any]:
        """
        Reconcile Kubernetes executions left RUNNING after a backend restart.

        The Kubernetes runner uses in-process async tasks to shepherd DAG progress,
        collect outputs, and schedule follow-up stages. If the backend restarts,
        those tasks disappear. Any Kubernetes-backed execution still marked RUNNING
        is therefore orphaned and must be failed cleanly so the user can retry.
        """
        recovered: List[int] = []
        errors: List[str] = []
        executions = get_running_executions()

        for execution in executions:
            parameters_used = getattr(execution, "parameters_used", None) or {}
            if not isinstance(parameters_used, dict):
                continue
            if str(parameters_used.get("backend") or "").strip().lower() != "kubernetes":
                continue

            job = get_job_by_id(execution.job_id)
            if not job:
                continue

            recovery_message = (
                "Kubernetes execution was interrupted because the backend restarted while this job was running. "
                "CASSIE marked the execution as failed during startup recovery. Please retry the job."
            )

            try:
                cleanup_summary = self.terminate_job_stages(execution.job_id, [execution])
                if cleanup_summary.get("errors"):
                    errors.extend(cleanup_summary["errors"])
            except Exception as exc:
                errors.append(f"job {execution.job_id}: failed to terminate orphaned stages ({exc})")

            stages = parameters_used.get("stages")
            if isinstance(stages, list):
                for stage in stages:
                    if not isinstance(stage, dict):
                        continue
                    if str(stage.get("status") or "").lower() in {
                        "pending",
                        "running",
                        "waiting_for_dependencies",
                        "waiting_for_resources",
                    }:
                        stage["status"] = "failed"
                        stage["completed_at"] = datetime.now().isoformat()
                        stage["error"] = recovery_message

            update_job_execution(
                execution.id,
                JobExecutionUpdate(
                    status=ExecutionStatus.FAILED,
                    error_message=recovery_message,
                    completed_at=datetime.now(),
                    parameters_used=parameters_used,
                ),
            )
            update_job(execution.job_id, job.user_id, JobUpdate(status=JobStatus.FAILED))
            settle_job_charge(execution.job_id, job.user_id, execution.id)
            recovered.append(execution.id)

        return {
            "recovered_execution_ids": recovered,
            "errors": errors,
        }

    def _run_kubectl(
        self,
        args: List[str],
        timeout: int = 60,
        cwd: Optional[str] = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["kubectl", *args]
        self._logger.info("Running kubectl command: %s", " ".join(cmd))
        try:
            return subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=cwd,
                check=False,
                env=_kubectl_env(),
            )
        except subprocess.TimeoutExpired:
            return subprocess.CompletedProcess(
                cmd,
                124,
                "",
                f"kubectl command timed out after {timeout} seconds",
            )


_kubernetes_runner: Optional[KubernetesPipelineRunner] = None


def _kubectl_env() -> Dict[str, str]:
    """Build an environment for kubectl that bypasses broken local proxy settings."""
    env = os.environ.copy()
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
        env.pop(key, None)

    no_proxy_hosts = {
        "localhost",
        "127.0.0.1",
        "host.docker.internal",
        "kubernetes.docker.internal",
    }
    existing_no_proxy = env.get("NO_PROXY") or env.get("no_proxy") or ""
    for item in existing_no_proxy.split(","):
        item = item.strip()
        if item:
            no_proxy_hosts.add(item)
    cassie_host_ip = env.get("CASSIE_HOST_IP", "").strip()
    if cassie_host_ip:
        no_proxy_hosts.add(cassie_host_ip)

    merged = ",".join(sorted(no_proxy_hosts))
    env["NO_PROXY"] = merged
    env["no_proxy"] = merged
    return env


def kubernetes_is_available() -> bool:
    """Return True when kubectl can reach a cluster."""
    timeout = max(1, int(os.getenv("KUBERNETES_AVAILABILITY_CHECK_TIMEOUT_SECONDS", "5")))
    probes = [
        ["kubectl", "get", "--raw=/readyz?verbose", f"--request-timeout={timeout}s"],
        ["kubectl", "get", "namespace", os.getenv("KUBERNETES_NAMESPACE", "default"), f"--request-timeout={timeout}s"],
    ]
    try:
        for cmd in probes:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout + 5,
                check=False,
                env=_kubectl_env(),
            )
            if result.returncode == 0:
                return True
        return False
    except Exception:
        return False


def get_kubernetes_pipeline_runner() -> KubernetesPipelineRunner:
    """Get or create the singleton Kubernetes pipeline runner."""
    global _kubernetes_runner
    if _kubernetes_runner is None:
        _kubernetes_runner = KubernetesPipelineRunner()
    return _kubernetes_runner


def get_pipeline_runner():
    """
    Return the active pipeline runner based on configuration.

    `EXECUTION_BACKEND` accepts:
    - `kubernetes`: require Kubernetes
    - `emulator`: require emulator
    - `auto`: treat Kubernetes as the default and fail if it is unavailable
    """
    backend = get_config().execution.backend
    if backend == "kubernetes":
        return get_kubernetes_pipeline_runner()
    if backend == "emulator":
        from backend.api.services.emulator_pipeline_runner import get_emulator_pipeline_runner

        return get_emulator_pipeline_runner()

    if kubernetes_is_available():
        return get_kubernetes_pipeline_runner()

    raise RuntimeError(
        "Kubernetes execution is configured, but the cluster is not reachable from the backend container. "
        "Check kubeconfig mounting and Docker Desktop Kubernetes connectivity."
    )

