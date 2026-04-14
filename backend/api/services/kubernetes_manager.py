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
import tempfile
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse, urlunparse

from backend.api.models.job_model import (
    ExecutionStatus,
    JobExecutionCreate,
    JobExecutionUpdate,
    JobStatus,
)
from backend.api.models.pipeline_model import FileCreate, FileType
from backend.api.services.job_execution_service import create_job_execution, update_job_execution
from backend.api.services.job_service import update_job
from backend.api.services.minio_client import get_minio_client
from backend.api.services.storage_service import create_file_record, get_file_by_id
from backend.api.utils.config_loader import get_config
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_id, get_tool_registry

logger = get_logger(__name__)


class KubernetesPipelineRunner:
    """Run CASSIE pipelines as sequential Kubernetes Jobs."""

    def __init__(self):
        self._config = get_config()
        self._logger = get_logger(__name__)
        self._resource_cache: Optional[Tuple[float, Dict[str, int]]] = None

    async def start_pipeline(
        self,
        job_id: int,
        user_id: int,
        workflow_id: int,
        input_files: List[int],
        execution_number: int = 1,
    ) -> Dict[str, Any]:
        """
        Create an execution record and schedule the Kubernetes pipeline.
        """
        namespace = self._config.kubernetes.namespace
        run_id = f"k8s-{job_id}-{execution_number}-{int(datetime.now().timestamp())}"
        work_dir = f"k8s://{namespace}/jobs/{run_id}"
        output_dir = f"{work_dir}/output"

        initial_parameters: Dict[str, Any] = {
            "backend": "kubernetes",
            "namespace": namespace,
            "workflow_id": workflow_id,
            "input_files": input_files,
            "stages": [],
        }

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

        from backend.api.models.job_model import JobUpdate

        update_job(job_id, user_id, JobUpdate(status=JobStatus.RUNNING))

        asyncio.create_task(
            self._run_pipeline_async(
                execution_id=execution.id,
                job_id=job_id,
                user_id=user_id,
                workflow_id=workflow_id,
                input_files=input_files,
                parameters_used=initial_parameters,
            )
        )

        return {
            "execution_id": execution.id,
            "status": execution.status.value,
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
    ) -> None:
        try:
            self._ensure_cluster_available()

            workflow = self._get_workflow(workflow_id, user_id)
            tools = self._resolve_workflow_tools(workflow)
            if not tools:
                raise ValueError(f"No valid tools found in workflow {workflow_id}")

            parameters_used["tool_sequence"] = [tool["id"] for tool in tools]
            self._persist_execution_state(execution_id, parameters_used)

            current_inputs = self._build_initial_inputs(user_id, input_files)
            if not current_inputs:
                raise ValueError("No input files available for Kubernetes execution")

            tool_versions: Dict[str, str] = {}

            for stage_number, tool in enumerate(tools, start=1):
                stage_job_name = self._make_job_name(job_id, execution_id, stage_number, tool["id"])
                stage_info: Dict[str, Any] = {
                    "stage_number": stage_number,
                    "tool_id": tool["id"],
                    "tool_name": tool["name"],
                    "kubernetes_job_name": stage_job_name,
                    "status": "pending",
                    "started_at": datetime.now().isoformat(),
                }
                parameters_used.setdefault("stages", []).append(stage_info)
                self._persist_execution_state(execution_id, parameters_used)

                tool_version = str(tool.get("docker", {}).get("image", "unknown"))
                tool_versions[tool["id"]] = tool_version

                try:
                    stage_outputs = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda: self._run_stage(
                            job_id=job_id,
                            execution_id=execution_id,
                            user_id=user_id,
                            stage_number=stage_number,
                            tool=tool,
                            stage_job_name=stage_job_name,
                            current_inputs=current_inputs,
                            stage_info=stage_info,
                            parameters_used=parameters_used,
                        ),
                    )
                except Exception as exc:
                    public_error = self._public_failure_message(str(exc), tool_name=tool.get("name"))
                    stage_info["status"] = "failed"
                    stage_info["completed_at"] = datetime.now().isoformat()
                    stage_info["error"] = public_error
                    self._persist_execution_state(execution_id, parameters_used, tool_versions=tool_versions)
                    raise RuntimeError(public_error) from exc

                stage_info["status"] = "completed"
                stage_info["completed_at"] = datetime.now().isoformat()
                stage_info["output_count"] = len(stage_outputs)
                self._persist_execution_state(execution_id, parameters_used, tool_versions=tool_versions)

                if tool.get("type") == "transform":
                    current_inputs = current_inputs + stage_outputs

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
        stage_info: Dict[str, Any],
        parameters_used: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        manifest = self._build_manifest(
            job_id=job_id,
            execution_id=execution_id,
            user_id=user_id,
            stage_number=stage_number,
            tool=tool,
            stage_job_name=stage_job_name,
            current_inputs=current_inputs,
        )
        namespace = self._config.kubernetes.namespace

        temp_manifest = tempfile.NamedTemporaryFile("w", suffix=".json", delete=False, encoding="utf-8")
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

            output_dir = self._copy_job_outputs(namespace, pod_name, tool["id"], stage_job_name)
            stage_outputs = self._upload_stage_outputs(
                local_output_dir=output_dir,
                job_id=job_id,
                execution_id=execution_id,
                user_id=user_id,
                stage_number=stage_number,
                tool=tool,
                current_inputs=current_inputs,
            )

            return stage_outputs
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
    ) -> Dict[str, Any]:
        config = self._config
        namespace = config.kubernetes.namespace
        minio_client = get_minio_client()
        bucket_name = minio_client.ensure_user_bucket(user_id=user_id)
        download_script = self._build_init_download_script(bucket_name, current_inputs)
        tool_plan = self._plan_tool_resources(tool["id"], current_inputs)
        tool_script = self._build_tool_script(tool, current_inputs, tool_plan)
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
                                        "memory": "128Mi",
                                        "ephemeral-storage": f'{tool_plan["init_storage_request_mib"]}Mi',
                                    },
                                    "limits": {
                                        "cpu": "500m",
                                        "memory": "512Mi",
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

    def _build_init_download_script(self, bucket_name: str, current_inputs: List[Dict[str, Any]]) -> str:
        lines = [
            "set -euo pipefail",
            "mkdir -p /workspace/input /workspace/output",
        ]
        for artifact in current_inputs:
            s3_key = artifact["s3_key"].replace('"', '\\"')
            filename = os.path.basename(artifact["filename"]).replace('"', '\\"')
            lines.append(
                f'aws --endpoint-url "$S3_ENDPOINT" s3 cp "s3://{bucket_name}/{s3_key}" "/workspace/input/{filename}"'
            )
        return "\n".join(lines)

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
    ) -> str:
        tool_plan = tool_plan or self._plan_tool_resources(tool["id"], current_inputs)
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
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {output_dir}",
                    f'fastqc --threads {tool_plan["threads"]} -o {output_dir} {fastqc_inputs}',
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
            low_resource_flag = " --only-assembler" if low_resource else ""
            kmers = str(tool_plan.get("kmers", "") or "").strip()
            kmers_flag = f" -k {kmers}" if kmers and re.fullmatch(r"\d+(,\d+)*", kmers) else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    "export TMPDIR=/workspace/tmp",
                    "mkdir -p /workspace/tmp",
                    f"mkdir -p {output_dir}/spades_out",
                    (
                        f'spades.py --threads {threads} --memory {memory_gb}{low_resource_flag}{kmers_flag} '
                        f'--tmp-dir /workspace/tmp '
                        f'-1 "{input_dir}/{r1}" -2 "{input_dir}/{r2}" '
                        f'-o "{output_dir}/spades_out"'
                    ),
                ]
            )

        if tool["id"] == "QUAST":
            assembly, reference = self._resolve_quast_inputs(classified["fasta"])
            threads = tool_plan["threads"]
            memory_flag = " --memory-efficient" if tool_plan["low_resource"] else ""
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {output_dir}/quast_out",
                    f'quast.py "{input_dir}/{os.path.basename(assembly["filename"])}" '
                    f'-r "{input_dir}/{os.path.basename(reference["filename"])}" '
                    f'-t {threads}{memory_flag} -o "{output_dir}/quast_out"',
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
            jellyfish_size = tool_plan.get("jellyfish_size", "50M")
            gs_out = f"{output_dir}/genomescope2_out"
            return self._wrap_tool_script(
                [
                    profile_note,
                    f"mkdir -p {gs_out}",
                    (
                        f'jellyfish count -C -m 21 -s {jellyfish_size} -t {threads} '
                        f'<({stream_expr}) -o "{gs_out}/reads.jf"'
                    ),
                    f'jellyfish histo "{gs_out}/reads.jf" > "{gs_out}/reads.histo"',
                    f'Rscript /opt/genomescope2.0/genomescope.R -i "{gs_out}/reads.histo" -o "{gs_out}" -k 21 -p 1',
                ]
            )

        raise ValueError(f"Kubernetes runner does not yet support tool {tool['id']}")

    def _tool_threads(self, tool_id: str, default: int) -> int:
        raw_value = os.getenv(f"{tool_id}_THREADS", os.getenv("CASSIE_TOOL_THREADS", str(default))).strip()
        try:
            return max(1, int(raw_value))
        except ValueError:
            return default

    def _tool_memory_gb(self, tool_id: str, default: int) -> int:
        raw_value = os.getenv(f"{tool_id}_MEMORY_GB", os.getenv("CASSIE_TOOL_MEMORY_GB", str(default))).strip()
        try:
            return max(1, int(raw_value))
        except ValueError:
            return default

    def _tool_flag(self, env_name: str, default: bool) -> bool:
        raw_value = os.getenv(env_name)
        if raw_value is None:
            return default
        return raw_value.strip().lower() in {"1", "true", "yes", "on"}

    def _plan_tool_resources(
        self,
        tool_id: str,
        current_inputs: Optional[List[Dict[str, Any]]] = None,
    ) -> Dict[str, Any]:
        """Choose the strongest safe tool profile for the current cluster."""
        capacity = self._detect_effective_cluster_capacity()
        cpu_millis = max(250, capacity["cpu_millis"])
        memory_mib = max(768, capacity["memory_mib"])
        tool_memory_budget_mib = max(512, min(int(memory_mib * 0.88), memory_mib - 256) - 128)
        whole_cpus = max(1, cpu_millis // 1000)
        resource_mode = os.getenv("CASSIE_RESOURCE_MODE", "adaptive").strip().lower()
        input_size_mib = self._estimate_input_size_mib(current_inputs or [])

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

            default_threads = 1 if low_resource else min(4, whole_cpus)
            default_memory_gb = 2 if low_resource else min(12, max(4, (tool_memory_budget_mib - 512) // 1024))
            default_kmers = "21" if low_resource else ""
            profile = "low-resource" if low_resource else "full"
            memory_limit = min(tool_memory_budget_mib, max(1024, default_memory_gb * 1024 + 512))

            if self._tool_flag("SPADES_REQUIRE_FULL", default=False) and low_resource:
                raise RuntimeError(
                    "SPAdes full correction mode does not fit the currently detected Kubernetes resources "
                    f"({cpu_millis}m CPU, {memory_mib}Mi memory). Increase Minikube/Docker resources or "
                    "unset SPADES_REQUIRE_FULL to allow low-resource assembly mode."
                )

            threads = self._tool_threads(tool_id, default_threads)
            memory_gb = min(self._tool_memory_gb(tool_id, default_memory_gb), max(1, memory_limit // 1024))
            kmers = self._env_value_or_default("SPADES_KMERS", default_kmers)

            return self._resource_plan(
                tool_id=tool_id,
                profile=profile,
                threads=threads,
                memory_gb=memory_gb,
                memory_limit_mib=memory_limit,
                cpu_limit_millis=min(max(1000, threads * 1000), max(1000, cpu_millis)),
                low_resource=low_resource,
                kmers=kmers,
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        if tool_id == "GENOMESCOPE2":
            default_threads = min(2, whole_cpus) if memory_mib >= 4096 else 1
            memory_limit = min(tool_memory_budget_mib, 2048 if memory_mib >= 3072 else 1536)
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=self._tool_threads(tool_id, default_threads),
                memory_gb=max(1, memory_limit // 1024),
                memory_limit_mib=memory_limit,
                cpu_limit_millis=min(max(1000, default_threads * 1000), max(1000, cpu_millis)),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
                extra={"jellyfish_size": self._genomescope_hash_size(memory_limit)},
            )

        if tool_id == "QUAST":
            default_threads = min(2, whole_cpus) if memory_mib >= 4096 else 1
            memory_limit = min(tool_memory_budget_mib, 2048 if memory_mib >= 4096 else 1500)
            return self._resource_plan(
                tool_id=tool_id,
                profile="adaptive",
                threads=self._tool_threads(tool_id, default_threads),
                memory_gb=max(1, memory_limit // 1024),
                memory_limit_mib=memory_limit,
                cpu_limit_millis=min(max(1000, default_threads * 1000), max(1000, cpu_millis)),
                low_resource=memory_mib < 4096,
                kmers="",
                input_size_mib=input_size_mib,
                capacity=capacity,
            )

        default_threads = min(2, whole_cpus) if memory_mib >= 4096 else 1
        memory_limit = min(tool_memory_budget_mib, 1024)
        return self._resource_plan(
            tool_id=tool_id,
            profile="adaptive",
            threads=self._tool_threads(tool_id, default_threads),
            memory_gb=max(1, memory_limit // 1024),
            memory_limit_mib=memory_limit,
            cpu_limit_millis=min(max(1000, default_threads * 1000), max(1000, cpu_millis)),
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
        cpu_request = self._env_value_or_default(
            f"{prefix}_CPU_REQUEST",
            "100m" if tool_id in {"FASTQC", "QUAST"} else "250m",
        )
        memory_request = self._env_value_or_default(
            f"{prefix}_MEMORY_REQUEST",
            "256Mi" if tool_id in {"FASTQC", "QUAST"} else "512Mi",
        )
        cpu_limit = self._env_value_or_default(f"{prefix}_CPU_LIMIT", self._format_cpu_quantity(cpu_limit_millis))
        memory_limit = self._env_value_or_default(f"{prefix}_MEMORY_LIMIT", f"{memory_limit_mib}Mi")
        storage_limit = self._env_value_or_default(f"{prefix}_STORAGE_LIMIT", f"{storage_limit_mib}Mi")

        plan = {
            "profile": profile,
            "threads": max(1, threads),
            "memory_gb": max(1, memory_gb),
            "low_resource": low_resource,
            "kmers": kmers,
            "input_size_mib": input_size_mib,
            "storage_limit_mib": storage_limit_mib,
            "storage_request_mib": storage_request_mib,
            "init_storage_request_mib": init_storage_request_mib,
            "storage_constrained": storage_limit_mib < self._estimated_required_storage_mib(
                tool_id, input_size_mib, low_resource
            ),
            "available_cpu_millis": capacity["cpu_millis"],
            "available_memory_mib": capacity["memory_mib"],
            "available_storage_mib": capacity.get("storage_mib", 0),
            "resources": {
                "requests": {
                    "cpu": cpu_request,
                    "memory": memory_request,
                    "ephemeral-storage": f"{storage_request_mib}Mi",
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
        if tool_id == "GENOMESCOPE2":
            return max(2048, padded_input + 2048)
        if tool_id == "QUAST":
            return max(1536, padded_input * 2 + 1024)
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

        reserve_mib = self._env_int("CASSIE_CLUSTER_STORAGE_RESERVE_MIB") or 2048
        max_workspace_mib = max(1024, cluster_storage_mib - reserve_mib)
        return min(max_workspace_mib, max(required_mib, 1024))

    def _genomescope_hash_size(self, memory_limit_mib: int) -> str:
        if memory_limit_mib >= 4096:
            return "100M"
        if memory_limit_mib >= 2048:
            return "50M"
        return "25M"

    def _detect_effective_cluster_capacity(self) -> Dict[str, int]:
        now = time.time()
        if self._resource_cache and now - self._resource_cache[0] < 60:
            return dict(self._resource_cache[1])

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

        self._resource_cache = (now, dict(capacity))
        return capacity

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

    def _classify_inputs(self, current_inputs: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
        fastq_exts = (".fastq", ".fq", ".fastq.gz", ".fq.gz")
        fasta_exts = (".fasta", ".fa", ".fna", ".fasta.gz", ".fa.gz", ".fna.gz")

        fastq: List[Dict[str, Any]] = []
        fasta: List[Dict[str, Any]] = []
        reads_like: List[Dict[str, Any]] = []

        for artifact in current_inputs:
            filename = artifact["filename"].lower()
            if filename.endswith(fastq_exts):
                fastq.append(artifact)
                reads_like.append(artifact)
            elif filename.endswith(fasta_exts):
                fasta.append(artifact)
                reads_like.append(artifact)

        fastq.sort(key=lambda item: item["filename"].lower())
        fasta.sort(key=lambda item: item["filename"].lower())
        reads_like.sort(key=lambda item: item["filename"].lower())

        return {"fastq": fastq, "fasta": fasta, "reads_like": reads_like}

    def _resolve_quast_inputs(self, fasta_files: List[Dict[str, Any]]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if len(fasta_files) < 2:
            raise ValueError("QUAST requires an assembly FASTA and a reference FASTA")

        assembly = None
        reference = None

        for artifact in fasta_files:
            filename = artifact["filename"].lower()
            if artifact.get("producer_tool_id") == "SPADES" or any(
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
        deadline = time.time() + timeout_seconds

        pod_name = ""

        while time.time() < deadline:
            pod_name = self._get_job_pod_name(job_name)
            if pod_name:
                pod_result = self._run_kubectl(
                    ["get", "pod", pod_name, "-n", namespace, "-o", "json"],
                    timeout=20,
                )
                if pod_result.returncode != 0:
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
                timeout=20,
            )
            if status_result.returncode != 0:
                raise RuntimeError(f"Failed to fetch Kubernetes Job status for {job_name}: {status_result.stderr.strip()}")

            payload = json.loads(status_result.stdout)
            status = payload.get("status", {})
            if status.get("failed", 0) >= 1:
                logs = self._get_stage_failure_logs(job_name)
                raise RuntimeError(
                    f"Kubernetes Job {job_name} failed.\n{logs[-4000:] if logs else 'No logs captured.'}"
                )

            time.sleep(poll_interval)

        raise TimeoutError(f"Kubernetes Job {job_name} exceeded timeout of {timeout_seconds} seconds")

    def _get_job_pod_name(self, job_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        result = self._run_kubectl(
            ["get", "pods", "-n", namespace, "-l", f"job-name={job_name}", "-o", "json"],
            timeout=20,
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
        copy_result = self._run_kubectl(
            ["cp", "-n", namespace, "-c", "artifacts", f"{pod_name}:/workspace/output/.", "output"],
            timeout=120,
            cwd=temp_dir,
        )
        if copy_result.returncode != 0:
            shutil.rmtree(temp_dir, ignore_errors=True)
            raise RuntimeError(f"Failed to copy outputs from pod {pod_name}: {copy_result.stderr.strip()}")
        return str(destination)

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
                            file_format=Path(filename).suffix.lstrip(".") or "dat",
                            size_bytes=upload_result["size"],
                            checksum=upload_result["checksum"],
                        )
                    )

                    stage_outputs.append(
                        {
                            "filename": safe_filename,
                            "s3_key": s3_key,
                            "source": "stage-output",
                            "producer_tool_id": tool["id"],
                        }
                    )
        finally:
            shutil.rmtree(Path(local_output_dir).parent, ignore_errors=True)

        return stage_outputs

    def _stage_output_display_name(
        self,
        tool: Dict[str, Any],
        rel_path: str,
        current_inputs: List[Dict[str, Any]],
    ) -> str:
        base_name = rel_path.replace("/", "_")
        if tool.get("id") != "GENOMESCOPE2":
            return base_name

        fastq_names = [
            self._compact_filename_label(os.path.basename(artifact.get("filename", "")))
            for artifact in self._classify_inputs(current_inputs)["fastq"]
            if artifact.get("filename")
        ]
        fastq_names = [name for name in fastq_names if name]
        if not fastq_names:
            return base_name

        prefix = "__".join(fastq_names)
        if len(prefix) > 140:
            visible = fastq_names[:2]
            remaining = len(fastq_names) - len(visible)
            prefix = "__".join(visible)
            if remaining > 0:
                prefix = f"{prefix}__plus_{remaining}_more"

        return f"{prefix}__{base_name}"

    def _compact_filename_label(self, filename: str) -> str:
        name = filename.strip()
        if not name:
            return ""

        lowered = name.lower()
        for suffix in (".fastq.gz", ".fq.gz", ".fastq", ".fq", ".fasta.gz", ".fa.gz", ".fna.gz", ".fasta", ".fa", ".fna"):
            if lowered.endswith(suffix):
                name = name[: -len(suffix)]
                break

        compact = re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("._-")
        return compact[:60]

    def _get_job_logs(self, job_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        result = self._run_kubectl(["logs", f"job/{job_name}", "-n", namespace, "-c", "tool"], timeout=60)
        if result.returncode != 0:
            return result.stderr.strip()
        return result.stdout

    def _get_pod_container_logs(self, pod_name: str, container_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        result = self._run_kubectl(["logs", pod_name, "-n", namespace, "-c", container_name], timeout=60)
        if result.returncode != 0:
            return result.stderr.strip()
        return result.stdout

    def _get_stage_failure_logs(self, job_name: str) -> str:
        pod_name = self._get_job_pod_name(job_name)
        if not pod_name:
            return self._get_job_logs(job_name)

        namespace = self._config.kubernetes.namespace
        pod_result = self._run_kubectl(["get", "pod", pod_name, "-n", namespace, "-o", "json"], timeout=20)
        if pod_result.returncode != 0:
            return pod_result.stderr.strip()

        pod_payload = json.loads(pod_result.stdout)
        for status in pod_payload.get("status", {}).get("initContainerStatuses", []) or []:
            terminated = (status.get("state") or {}).get("terminated")
            waiting = (status.get("state") or {}).get("waiting")
            if terminated or waiting:
                return self._get_pod_container_logs(pod_name, status.get("name", "fetch-inputs"))

        return self._get_job_logs(job_name)

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

    def _run_kubectl(
        self,
        args: List[str],
        timeout: int = 60,
        cwd: Optional[str] = None,
    ) -> subprocess.CompletedProcess[str]:
        cmd = ["kubectl", *args]
        self._logger.info("Running kubectl command: %s", " ".join(cmd))
        return subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            check=False,
            env=_kubectl_env(),
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
    timeout = max(5, int(os.getenv("KUBERNETES_CLUSTER_CHECK_TIMEOUT_SECONDS", "60")))
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
