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
                    stage_info["status"] = "failed"
                    stage_info["completed_at"] = datetime.now().isoformat()
                    stage_info["error"] = str(exc)
                    self._persist_execution_state(execution_id, parameters_used, tool_versions=tool_versions)
                    raise

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
            self._logger.error(
                f"Kubernetes pipeline execution failed for job {job_id}, execution {execution_id}: {exc}",
                exc_info=True,
            )
            update_job_execution(
                execution_id,
                JobExecutionUpdate(
                    status=ExecutionStatus.FAILED,
                    error_message=str(exc),
                    completed_at=datetime.now(),
                    parameters_used=parameters_used,
                ),
            )
            from backend.api.models.job_model import JobUpdate

            update_job(job_id, user_id, JobUpdate(status=JobStatus.FAILED))

    def _ensure_cluster_available(self) -> None:
        result = self._run_kubectl(["cluster-info"], timeout=20)
        if result.returncode != 0:
            raise RuntimeError(
                "Kubernetes cluster is not reachable from the backend container. "
                "Ensure Docker Desktop Kubernetes is enabled and kubeconfig is mounted."
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
        tool_script = self._build_tool_script(tool, current_inputs)

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
                        "volumes": [{"name": "workspace", "emptyDir": {}}],
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
                                "volumeMounts": [{"name": "workspace", "mountPath": "/workspace"}],
                            },
                            {
                                "name": "artifacts",
                                "image": "busybox:1.36.1",
                                "imagePullPolicy": "IfNotPresent",
                                "command": ["sh", "-lc"],
                                "args": ["while true; do sleep 30; done"],
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

    def _build_tool_script(self, tool: Dict[str, Any], current_inputs: List[Dict[str, Any]]) -> str:
        classified = self._classify_inputs(current_inputs)
        input_dir = "/workspace/input"
        output_dir = "/workspace/output"

        if tool["id"] == "FASTQC":
            reads = classified["reads_like"]
            if not reads:
                raise ValueError("FastQC requires at least one FASTQ/FASTA input file")
            input_file = os.path.basename(reads[0]["filename"])
            return "\n".join(
                [
                    "set -euo pipefail",
                    f"mkdir -p {output_dir}",
                    f'fastqc -o {output_dir} "{input_dir}/{input_file}"',
                ]
            )

        if tool["id"] == "SPADES":
            fastq_reads = self._select_fastq_inputs(classified["fastq"], required=2)
            if len(fastq_reads) < 2:
                raise ValueError("SPAdes requires paired-end reads (at least two FASTQ files)")
            r1 = os.path.basename(fastq_reads[0]["filename"])
            r2 = os.path.basename(fastq_reads[1]["filename"])
            return "\n".join(
                [
                    "set -euo pipefail",
                    f"mkdir -p {output_dir}/spades_out",
                    f'spades.py -1 "{input_dir}/{r1}" -2 "{input_dir}/{r2}" -o "{output_dir}/spades_out"',
                ]
            )

        if tool["id"] == "QUAST":
            assembly, reference = self._resolve_quast_inputs(classified["fasta"])
            return "\n".join(
                [
                    "set -euo pipefail",
                    f"mkdir -p {output_dir}/quast_out",
                    f'quast.py "{input_dir}/{os.path.basename(assembly["filename"])}" '
                    f'-r "{input_dir}/{os.path.basename(reference["filename"])}" '
                    f'-o "{output_dir}/quast_out"',
                ]
            )

        if tool["id"] == "GENOMESCOPE2":
            fastq_reads = self._select_fastq_inputs(classified["fastq"], required=2)
            if not fastq_reads:
                raise ValueError("GenomeScope2 requires FASTQ reads")
            inputs = [os.path.basename(item["filename"]) for item in fastq_reads[:2]]
            gzip_commands: List[str] = []
            zcat_inputs: List[str] = []
            for index, input_name in enumerate(inputs, start=1):
                src = f"{input_dir}/{input_name}"
                gz = f"{input_dir}/reads_{index}.fastq.gz"
                if input_name.endswith(".gz"):
                    gzip_commands.append(f'cp "{src}" "{gz}"')
                else:
                    gzip_commands.append(f'gzip -c "{src}" > "{gz}"')
                zcat_inputs.append(gz)

            zcat_expr = " ".join(f'"{path}"' for path in zcat_inputs)
            gs_out = f"{output_dir}/genomescope2_out"
            return "\n".join(
                [
                    "set -euo pipefail",
                    f"mkdir -p {gs_out}",
                    *gzip_commands,
                    f'jellyfish count -C -m 21 -s 100M -t 4 <(zcat {zcat_expr}) -o "{gs_out}/reads.jf"',
                    f'jellyfish histo "{gs_out}/reads.jf" > "{gs_out}/reads.histo"',
                    f'Rscript /opt/genomescope2.0/genomescope.R -i "{gs_out}/reads.histo" -o "{gs_out}" -k 21 -p 1',
                ]
            )

        raise ValueError(f"Kubernetes runner does not yet support tool {tool['id']}")

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
                container_statuses = pod_payload.get("status", {}).get("containerStatuses", []) or []
                tool_status = next(
                    (status for status in container_statuses if status.get("name") == "tool"),
                    None,
                )
                if tool_status:
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
                logs = self._get_job_logs(job_name)
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
                    safe_filename = rel_path.replace("/", "_")
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

    def _get_job_logs(self, job_name: str) -> str:
        namespace = self._config.kubernetes.namespace
        result = self._run_kubectl(["logs", f"job/{job_name}", "-n", namespace, "-c", "tool"], timeout=60)
        if result.returncode != 0:
            return result.stderr.strip()
        return result.stdout

    def _cluster_visible_minio_endpoint(self, endpoint: str) -> str:
        override = self._config.kubernetes.minio_endpoint.strip()
        if override:
            return override

        parsed = urlparse(endpoint)
        host = parsed.hostname or ""
        if host in {"127.0.0.1", "localhost"}:
            netloc = parsed.netloc.replace(host, "host.docker.internal")
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

    merged = ",".join(sorted(no_proxy_hosts))
    env["NO_PROXY"] = merged
    env["no_proxy"] = merged
    return env


def kubernetes_is_available() -> bool:
    """Return True when kubectl can reach a cluster."""
    try:
        result = subprocess.run(
            ["kubectl", "cluster-info"],
            capture_output=True,
            text=True,
            timeout=15,
            check=False,
            env=_kubectl_env(),
        )
        return result.returncode == 0
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
