"""
Emulator-based pipeline runner that uses the existing emulation system.

This integrates with the emulation/ directory to run pipelines in Docker containers
using dockerized tools (FastQC, SPAdes, etc.).
"""

import os
import sys
import json
import asyncio
import shutil
import tarfile
import tempfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import docker

# Add project root to path so we can import emulation as a package
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from backend.api.services.job_execution_service import (
    create_job_execution,
    update_job_execution,
    get_job_execution_by_id
)
from backend.api.services.job_service import update_job
from backend.api.services.job_archive_service import prewarm_job_outputs_zip
from backend.api.services.storage_service import get_file_by_id, create_file_record
from backend.api.models.pipeline_model import FileCreate, FileType
from backend.api.services.minio_client import get_minio_client
from backend.api.models.job_model import (
    JobExecutionCreate,
    JobExecutionUpdate,
    ExecutionStatus,
    JobStatus
)
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_id, get_tool_registry

logger = get_logger(__name__)

# Import emulator modules as a package
try:
    from emulation.tenant_commands import add_tenant, get_tenant_container
    from emulation.nextflow_manager import run_pipeline as emulator_run_pipeline, get_tool_list
    from emulation.docker_commands import ensure_vms, client as docker_client
    logger.info("Successfully imported emulator modules")
except ImportError as e:
    logger.error(f"Could not import emulator modules: {e}", exc_info=True)
    logger.error("Pipeline execution will fail. Check emulation/ directory and imports.")
    # Set to None so we can check later
    add_tenant = None
    get_tenant_container = None
    emulator_run_pipeline = None
    get_tool_list = None
    ensure_vms = None
    docker_client = None


def _ensure_emulator_dependencies() -> None:
    """Recover emulator imports lazily if startup-time imports failed."""
    global add_tenant, get_tenant_container, emulator_run_pipeline, get_tool_list, ensure_vms, docker_client

    if callable(add_tenant) and callable(get_tenant_container) and callable(emulator_run_pipeline) and callable(ensure_vms):
        return

    try:
        from emulation.tenant_commands import add_tenant as add_tenant_fn, get_tenant_container as get_tenant_container_fn
        from emulation.nextflow_manager import run_pipeline as emulator_run_pipeline_fn, get_tool_list as get_tool_list_fn
        from emulation.docker_commands import ensure_vms as ensure_vms_fn, client as docker_client_obj

        add_tenant = add_tenant_fn
        get_tenant_container = get_tenant_container_fn
        emulator_run_pipeline = emulator_run_pipeline_fn
        get_tool_list = get_tool_list_fn
        ensure_vms = ensure_vms_fn
        docker_client = docker_client_obj
        logger.info("Recovered emulator module imports lazily")
    except ImportError as e:
        logger.error(f"Lazy emulator import failed: {e}", exc_info=True)
        raise RuntimeError(
            "Emulator dependencies could not be imported. Check the emulation modules and Docker availability."
        ) from e


class EmulatorPipelineRunner:
    """
    Pipeline runner that uses the emulation system.
    
    This runs pipelines in Docker containers using the emulator's tenant system
    and dockerized tools (FastQC, SPAdes, etc.).
    """
    
    def __init__(self):
        """Initialize emulator pipeline runner."""
        self._logger = get_logger(__name__)
        # Don't ensure VMs here - it's blocking and will be done in background task
        # VMs will be ensured when first pipeline starts

    def _copy_local_file_to_container(self, tenant_container, local_path: str, tenant_file_path: str) -> None:
        """Copy a local file into a container without relying on the docker CLI."""
        container_dir = os.path.dirname(tenant_file_path) or "/"
        tenant_container.exec_run(['mkdir', '-p', container_dir], user='root')

        tar_fd, tar_path = tempfile.mkstemp(suffix=".tar")
        os.close(tar_fd)
        try:
            with tarfile.open(tar_path, mode="w") as tar_handle:
                tar_handle.add(local_path, arcname=os.path.basename(tenant_file_path))

            with open(tar_path, "rb") as tar_stream:
                success = tenant_container.put_archive(container_dir, tar_stream)

            if not success:
                raise RuntimeError(f"Failed to copy {local_path} into container path {tenant_file_path}")
        finally:
            try:
                os.unlink(tar_path)
            except OSError:
                pass

    def _copy_file_from_container(self, tenant_container, container_file_path: str, local_file_path: str) -> None:
        """Copy a single file from a container without relying on the docker CLI."""
        stream, _ = tenant_container.get_archive(container_file_path)

        tar_fd, tar_path = tempfile.mkstemp(suffix=".tar")
        os.close(tar_fd)
        extract_dir = tempfile.mkdtemp(prefix="cassie_extract_")
        try:
            with open(tar_path, "wb") as tar_stream:
                for chunk in stream:
                    tar_stream.write(chunk)

            with tarfile.open(tar_path, mode="r") as tar_handle:
                members = [member for member in tar_handle.getmembers() if member.isfile()]
                if not members:
                    raise RuntimeError(f"No file payload found in archive for {container_file_path}")

                source = tar_handle.extractfile(members[0])
                if source is None:
                    raise RuntimeError(f"Could not extract {container_file_path} from container archive")

                os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                with source, open(local_file_path, "wb") as output_file:
                    shutil.copyfileobj(source, output_file)
        finally:
            shutil.rmtree(extract_dir, ignore_errors=True)
            try:
                os.unlink(tar_path)
            except OSError:
                pass

    def _resolve_workflow_tool_indices(self, workflow: Dict[str, Any]) -> List[int]:
        """Resolve workflow tools from stable ids first, then legacy display names."""
        resolved_indices: List[int] = []
        available_tools = get_tool_registry()
        by_id = {tool["id"]: idx for idx, tool in enumerate(available_tools)}
        by_name = {tool["name"].lower(): idx for idx, tool in enumerate(available_tools)}

        for step in workflow.get("workflow_steps", []) or []:
            tool_id = step.get("tool")
            if tool_id in by_id and by_id[tool_id] not in resolved_indices:
                resolved_indices.append(by_id[tool_id])

        if resolved_indices:
            return resolved_indices

        for item in workflow.get("tools_used", []) or []:
            key = str(item).strip()
            idx = by_id.get(key.upper())
            if idx is None:
                idx = by_name.get(key.lower())
            if idx is not None and idx not in resolved_indices:
                resolved_indices.append(idx)

        return resolved_indices

    def _ensure_tenant_container_running(self, container, tenant_name: str, user_id: int) -> None:
        """Ensure the tenant container and its backing VM are both running."""
        import time

        container.reload()
        if container.status == "running":
            return

        vm_name = None
        try:
            network_mode = (container.attrs or {}).get("HostConfig", {}).get("NetworkMode", "")
            if isinstance(network_mode, str) and network_mode.startswith("container:"):
                vm_name = network_mode.split(":", 1)[1]
        except Exception:
            vm_name = None

        if not vm_name:
            from backend.api.database.db_init import get_db_connection
            with get_db_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT vm_name FROM tenants WHERE name = %s AND user_id = %s", (tenant_name, user_id))
                row = cur.fetchone()
                cur.close()
                if row:
                    vm_name = row[0]

        if vm_name:
            from emulation.docker_commands import start_vm
            start_vm(vm_name)
            time.sleep(2)

        container.start()
        time.sleep(1)
        container.reload()
        if container.status != "running":
            raise RuntimeError(f"Tenant container '{container.name}' is not running (status={container.status})")

        try:
            from emulation.docker_commands import sync_tool_scripts
            sync_tool_scripts(container)
        except Exception as e:
            self._logger.warning(f"Could not sync tool scripts into tenant container {container.name}: {e}")
    
    async def start_pipeline(
        self,
        job_id: int,
        user_id: int,
        workflow_id: int,
        input_files: List[int],
        execution_number: int = 1
    ) -> Dict[str, Any]:
        """
        Start a pipeline execution using the emulator system.
        
        This method returns immediately after creating the execution record.
        All heavy setup work (Docker operations, file downloads) is done
        asynchronously in _run_pipeline_async to avoid blocking the HTTP response.
        
        Args:
            job_id: Job ID
            user_id: User ID
            workflow_id: Workflow ID
            input_files: List of input file IDs
            execution_number: Execution attempt number
            
        Returns:
            dict: Execution details
        """
        try:
            # Create execution record immediately (lightweight database operation)
            nextflow_run_id = f"emulator-{job_id}-{execution_number}-{int(datetime.now().timestamp())}"
            work_dir = f"/tmp/cassie/job_{job_id}/exec_{execution_number}"
            output_dir = f"{work_dir}/output"
            
            # Determine initial status: PENDING if no files, RUNNING if files exist
            initial_status = ExecutionStatus.PENDING if not input_files else ExecutionStatus.RUNNING
            
            execution_data = JobExecutionCreate(
                job_id=job_id,
                execution_number=execution_number,
                status=initial_status,  # PENDING if no files, RUNNING if files exist
                nextflow_run_id=nextflow_run_id,
                work_dir=work_dir,
                output_dir=output_dir,
                process_id=None,
                tool_versions={"fastqc": "0.12.1"},
                parameters_used={"input_files": input_files, "workflow_id": workflow_id},
                started_at=datetime.now() if input_files else None  # Only set started_at if actually starting
            )
            
            execution = create_job_execution(execution_data)
            
            # Update job status based on execution status
            from backend.api.models.job_model import JobUpdate
            job_status = JobStatus.PENDING if initial_status == ExecutionStatus.PENDING else JobStatus.RUNNING
            update_job(job_id, user_id, JobUpdate(status=job_status))
            
            # Only schedule setup/pipeline execution if files are provided
            # If no files, execution stays PENDING until files are uploaded
            if input_files:
                # Schedule all heavy setup work to run asynchronously
                # This includes: Docker operations, file downloads, etc.
                async_task = asyncio.create_task(self._setup_and_run_pipeline_async(
                    execution.id,
                    job_id,
                    user_id,
                    workflow_id,
                    input_files,
                    execution_number,
                    work_dir,
                    output_dir
                ))
                
                # Add error callback to catch any unhandled exceptions
                def handle_task_exception(task):
                    try:
                        task.result()  # This will raise if task failed
                    except Exception as e:
                        self._logger.error(
                            f"Unhandled exception in async pipeline task for job {job_id}, execution {execution.id}: {e}",
                            exc_info=True
                        )
                        # Update status to failed
                        try:
                            update_data = JobExecutionUpdate(
                                status=ExecutionStatus.FAILED,
                                error_message=f"Unhandled exception: {str(e)}",
                                completed_at=datetime.now()
                            )
                            update_job_execution(execution.id, update_data)
                            from backend.api.models.job_model import JobUpdate
                            update_job(job_id, user_id, JobUpdate(status=JobStatus.FAILED))
                        except Exception as update_error:
                            self._logger.error(f"Failed to update job status after error: {update_error}")
                
                async_task.add_done_callback(handle_task_exception)
                self._logger.info(f"Scheduled pipeline execution for job {job_id}, execution {execution.id}")
            else:
                self._logger.info(
                    f"Execution {execution.id} created with PENDING status for job {job_id}. "
                    f"Will start when input files are available."
                )
            
            return {
                'execution_id': execution.id,
                'nextflow_run_id': nextflow_run_id,
                'work_dir': work_dir,
                'output_dir': output_dir,
                'started_at': execution.started_at.isoformat() if execution.started_at else None
            }
            
        except Exception as e:
            self._logger.error(f"Error starting pipeline: {e}", exc_info=True)
            raise
    
    async def _setup_and_run_pipeline_async(
        self,
        execution_id: int,
        job_id: int,
        user_id: int,
        workflow_id: int,
        input_files: List[int],
        execution_number: int,
        work_dir: str,
        output_dir: str
    ):
        """Setup pipeline (Docker, file downloads) and then run it - all in background."""
        try:
            _ensure_emulator_dependencies()
            self._logger.info(f"Starting setup for job {job_id}, execution {execution_id}")
            
            # Run blocking operations in thread pool to avoid blocking the event loop
            import asyncio
            loop = asyncio.get_event_loop()
            
            # Ensure VMs are set up (only check once, skip if already verified)
            # VMs are long-lived containers, so we only need to verify they exist
            # This is a lightweight check that only creates VMs if they don't exist
            if not hasattr(self.__class__, '_vms_verified'):
                self._logger.info("Checking VMs are set up...")
                await loop.run_in_executor(None, lambda: ensure_vms())
                self.__class__._vms_verified = True
                self._logger.info("VMs verified")
            
            # Ensure user has a tenant container (blocking Docker operation)
            tenant_name = f"user_{user_id}"
            tenant_container = await loop.run_in_executor(
                None,
                lambda: self._get_or_create_tenant(tenant_name, user_id, job_id)
            )
            
            # Get workflow to determine tool indices
            from backend.api.services.workflow_service import get_workflow_by_id
            workflow = get_workflow_by_id(workflow_id, user_id=user_id)
            if not workflow:
                raise ValueError(f"Workflow {workflow_id} not found")
            
            self._logger.info(f"Retrieved workflow {workflow_id}: {workflow.get('name', 'Unknown')}")
            self._logger.info(f"Workflow tools_used: {workflow.get('tools_used', [])}")
            
            tool_indices = self._resolve_workflow_tool_indices(workflow)
            tools_used = workflow.get('tools_used', [])
            for idx in tool_indices:
                tool = get_tool_by_id(get_tool_registry()[idx]["id"])
                if tool:
                    self._logger.info(f"Resolved workflow tool '{tool['id']}' to index {idx}")
            
            if not tool_indices:
                raise ValueError(f"No valid tools found in workflow {workflow_id}. tools_used: {tools_used}")
            
            # Automatically order tools based on dependencies
            # Check input files to determine capabilities
            # input_files is a list of file IDs, so we need to fetch the actual file records
            has_reference = False
            has_assembly = False
            has_paired_end = False
            fastq_count = 0
            fasta_count = 0
            
            if input_files:
                from backend.api.services.storage_service import get_file_by_id
                for file_id in input_files:
                    try:
                        file_record = get_file_by_id(file_id, user_id=user_id)
                        if file_record:
                            filename_lower = file_record.filename.lower()
                            if filename_lower.endswith(('.fasta', '.fa', '.fna', '.fasta.gz', '.fa.gz', '.fna.gz')):
                                fasta_count += 1
                                self._logger.info(f"Detected FASTA file: {file_record.filename}")
                            elif filename_lower.endswith(('.fastq', '.fq', '.fastq.gz', '.fq.gz')):
                                fastq_count += 1
                    except Exception as e:
                        self._logger.warning(f"Could not check file {file_id}: {e}")
            
            # Determine if we have assembly and/or reference files
            # Check if QUAST is selected to determine if 2 FASTA files = assembly + reference
            has_quast = False
            has_spades = False
            if tool_indices:
                try:
                    from emulation.nextflow_manager import AVAILABLE_TOOLS
                    has_quast = any(
                        idx < len(AVAILABLE_TOOLS) and AVAILABLE_TOOLS[idx]["id"] == "QUAST"
                        for idx in tool_indices
                    )
                    has_spades = any(
                        idx < len(AVAILABLE_TOOLS) and AVAILABLE_TOOLS[idx]["id"] == "SPADES"
                        for idx in tool_indices
                    )
                except ImportError:
                    self._logger.warning("Could not import AVAILABLE_TOOLS to check for QUAST/SPAdes")
            
            if fasta_count >= 2 and has_quast and not has_spades:
                # 2+ FASTA files with QUAST (no SPAdes) = assembly + reference
                has_assembly = True
                has_reference = True
                self._logger.info(f"Detected {fasta_count} FASTA files with QUAST (no SPAdes): assuming 1 assembly + 1 reference")
            elif fasta_count >= 1:
                # 1 FASTA file: if SPAdes is selected, it's a reference; otherwise assume reference
                has_reference = True
                if has_spades:
                    self._logger.info(f"Detected reference genome file (SPAdes will generate assembly)")
                else:
                    self._logger.info(f"Detected reference genome file")
            
            # SPAdes requires paired-end reads (2 FASTQ files)
            has_paired_end = fastq_count >= 2
            if fastq_count == 1:
                self._logger.info(f"Detected single-end reads (1 FASTQ file). SPAdes will be filtered out if selected.")
            elif fastq_count >= 2:
                self._logger.info(f"Detected paired-end reads ({fastq_count} FASTQ files). SPAdes can run.")
            
            from backend.api.services.workflow_service import order_tools_by_dependencies
            tool_indices = order_tools_by_dependencies(
                tool_indices, 
                has_reference_file=has_reference, 
                has_paired_end_reads=has_paired_end,
                has_assembly_file=has_assembly
            )
            
            if not tool_indices:
                raise ValueError("No valid tools remaining after dependency filtering")
            
            self._logger.info(f"Final tool indices for pipeline (ordered): {tool_indices}")
            
            # Download files from MinIO to tenant container (blocking I/O operations)
            input_path = await loop.run_in_executor(
                None,
                lambda: self._download_input_files(tenant_container, input_files, user_id, tool_indices)
            )
            
            # Update execution status to RUNNING
            update_data = JobExecutionUpdate(status=ExecutionStatus.RUNNING)
            update_job_execution(execution_id, update_data)
            from backend.api.models.job_model import JobUpdate
            update_job(job_id, user_id, JobUpdate(status=JobStatus.RUNNING))
            
            self._logger.info(f"Setup complete for job {job_id}, execution {execution_id}. Starting pipeline...")
            
            # Now run the actual pipeline
            await self._run_pipeline_async(
                execution_id,
                job_id,
                user_id,
                tenant_container,
                input_path,
                tool_indices,
                output_dir
            )
            
        except Exception as e:
            self._logger.error(f"Error in setup/run pipeline for job {job_id}, execution {execution_id}: {e}", exc_info=True)
            update_data = JobExecutionUpdate(
                status=ExecutionStatus.FAILED,
                error_message=str(e),
                completed_at=datetime.now()
            )
            update_job_execution(execution_id, update_data)
            from backend.api.models.job_model import JobUpdate
            update_job(job_id, user_id, JobUpdate(status=JobStatus.FAILED))
    
    def _get_or_create_tenant(self, tenant_name: str, user_id: int, job_id: Optional[int] = None):
        """Get or create tenant container (blocking operation).
        
        Args:
            tenant_name: Name of the tenant
            user_id: User ID
            job_id: Optional job ID to get vm_name from job
        """
        _ensure_emulator_dependencies()
        if get_tenant_container is None or add_tenant is None:
            error_msg = "Emulator modules not imported. Cannot create tenant. Check backend logs for import errors."
            self._logger.error(error_msg)
            raise RuntimeError(error_msg)
        
        try:
            # Try to get existing tenant container first (most common case)
            container = get_tenant_container(tenant_name, user_id=user_id)
            self._ensure_tenant_container_running(container, tenant_name, user_id)
            self._logger.info(f"Using existing tenant container: {container.name}")
            return container
        except Exception as e:
            # Container doesn't exist - need to create it
            self._logger.info(f"[INFO] Tenant container not found: {type(e).__name__}: {str(e)}")
            
            # Check if tenant exists in database but container is missing (only if it's a NotFound error)
            if "NotFound" in str(type(e).__name__) or "not found" in str(e).lower():
                from backend.api.database.db_init import get_db_connection
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT id, vm_name FROM tenants WHERE name = %s AND user_id = %s", (tenant_name, user_id))
                    tenant_row = cur.fetchone()
                    cur.close()
                    if tenant_row:
                        self._logger.warning(f"Tenant '{tenant_name}' exists in database but container is missing - recreating...")
                        # Tenant exists in DB but container is missing - try to recreate
                        tenant_id, vm_name = tenant_row
                        try:
                            from emulation.docker_commands import create_tenant_user, divide_resources_for_tenant
                            # Get resource hints
                            try:
                                cpu_quota, mem_limit = divide_resources_for_tenant(vm_name)
                            except Exception:
                                cpu_quota, mem_limit = None, None
                            # Recreate container
                            cont = create_tenant_user(vm_name, tenant_name, user_id, cpu_quota=cpu_quota, mem_limit=mem_limit)
                            self._ensure_tenant_container_running(cont, tenant_name, user_id)
                            self._logger.info(f"[SUCCESS] Recreated tenant container: {cont.name}")
                            return cont
                        except Exception as recreate_error:
                            self._logger.error(f"Failed to recreate container: {recreate_error}")
                            # Fall through to create new tenant
            
            # Create new tenant (either doesn't exist in DB, or recreation failed)
            self._logger.info(f"Creating new tenant container for user {user_id}...")
            
            try:
                # Verify user exists in database
                with get_db_connection() as conn:
                    cur = conn.cursor()
                    cur.execute("SELECT username FROM users WHERE id = %s", (user_id,))
                    row = cur.fetchone()
                    if not row:
                        raise ValueError(f"User with id {user_id} not found in database")
                    cur.close()
                
                # Get vm_name from job if available
                vm_name = None
                if job_id:
                    try:
                        from backend.api.services.job_service import get_job_by_id
                        job = get_job_by_id(job_id, user_id=user_id)
                        if job and job.vm_name:
                            vm_name = job.vm_name
                            self._logger.info(f"Using VM '{vm_name}' from job {job_id}")
                    except Exception as e:
                        self._logger.warning(f"Could not get vm_name from job {job_id}: {e}")
                
                # Create tenant (handles bucket creation internally)
                # Pass vm_name if available from job
                add_tenant(tenant_name, vm_name=vm_name, user_id=user_id)
                
                # Get the newly created container
                container = get_tenant_container(tenant_name, user_id=user_id)
                self._ensure_tenant_container_running(container, tenant_name, user_id)
                self._logger.info(f"Tenant container created: {container.name}")
                self._logger.info(f"Container status: {container.status}")
                self._logger.info(f"="*60)
                return container
            except Exception as create_error:
                error_msg = f"Failed to create tenant for user {user_id}: {create_error}"
                self._logger.error("="*60)
                self._logger.error("TENANT CREATION FAILED")
                self._logger.error("="*60)
                self._logger.error(f"Error type: {type(create_error).__name__}")
                self._logger.error(f"Error message: {str(create_error)}")
                self._logger.error(f"Full traceback:", exc_info=True)
                self._logger.error("="*60)
                raise RuntimeError(error_msg) from create_error
    
    def _download_input_files(self, tenant_container, input_files: List[int], user_id: int, tool_indices: Optional[List[int]] = None) -> str:
        """Download input files from MinIO to tenant container (blocking I/O)."""
        minio_client = get_minio_client()
        input_paths = []
        
        self._logger.info(f"Starting file download for {len(input_files)} file(s) to tenant container {tenant_container.name}")
        
        for idx, file_id in enumerate(input_files, 1):
            self._logger.info(f"[{idx}/{len(input_files)}] Downloading file {file_id}...")
            
            file_record = get_file_by_id(file_id, user_id=user_id)
            if not file_record:
                raise ValueError(f"File {file_id} not found")
            
            file_size = file_record.size_bytes or 0
            self._logger.info(f"File {file_id}: {file_record.filename} (size: {file_size} bytes)")
            
            # Download file from MinIO to tenant container
            tenant_file_path = f"/data/input_{file_id}_{file_record.filename}"
            
            # Download from MinIO to local temp, then copy to container
            # Create temp file path but don't keep it open (Windows issue)
            tmp_file = tempfile.NamedTemporaryFile(delete=False)
            tmp_path = tmp_file.name
            tmp_file.close()  # Close immediately so boto3 can write to it
            
            try:
                self._logger.info(f"Downloading from MinIO (s3_key: {file_record.s3_key})...")
                minio_client.download_file(
                    user_id=user_id,
                    s3_key=file_record.s3_key,
                    local_path=tmp_path
                )
                self._logger.info(f"Downloaded to temp file: {tmp_path}")
                
                self._logger.info(f"Copying file to tenant container at {tenant_file_path}...")
                self._copy_local_file_to_container(tenant_container, tmp_path, tenant_file_path)
                
                self._logger.info(f"[{idx}/{len(input_files)}] File {file_id} successfully copied to container")
            finally:
                # Clean up temp file
                try:
                    os.unlink(tmp_path)
                except Exception as e:
                    self._logger.warning(f"Failed to delete temp file {tmp_path}: {e}")
            
            input_paths.append(tenant_file_path)
        
        # Use first input file path
        if not input_paths:
            raise ValueError("No input files provided")
        
        # Format input path for Nextflow pipeline
        # Check file types to determine format
        fastq_files = [
            p for p in input_paths
            if p.endswith(('.fastq', '.fq', '.fastq.gz', '.fq.gz'))
        ]
        fasta_files = [
            p for p in input_paths
            if p.endswith(('.fasta', '.fa', '.fna', '.fasta.gz', '.fa.gz', '.fna.gz'))
        ]
        
        # Format input arguments
        formatted_parts = []
        
        # Handle paired-end FASTQ files (2 FASTQ files = paired-end reads for SPAdes)
        # AFTER: mimic the CLI behavior that you know works
        if len(fastq_files) == 2:
            # Use two separate -fastq args, like the interactive client:
            #   -fastq fwd.fq -fastq rev.fq
            formatted_parts.append(f"-fastq {fastq_files[0]}")
            formatted_parts.append(f"-fastq {fastq_files[1]}")
            self._logger.info(f"Detected paired-end reads: {fastq_files[0]} and {fastq_files[1]}")
        elif len(fastq_files) == 1:
            formatted_parts.append(f"-fastq {fastq_files[0]}")
        elif len(fastq_files) > 2:
            fastq_list = ' '.join(fastq_files)
            formatted_parts.append(f"-fastq {fastq_list}")

        # Handle FASTA files
        # Check if QUAST is selected but SPAdes is not (need to distinguish assembly vs reference)
        has_quast = False
        has_spades = False
        if tool_indices:
            try:
                from emulation.nextflow_manager import AVAILABLE_TOOLS
                has_quast = any(
                    idx < len(AVAILABLE_TOOLS) and AVAILABLE_TOOLS[idx]["id"] == "QUAST"
                    for idx in tool_indices
                )
                has_spades = any(
                    idx < len(AVAILABLE_TOOLS) and AVAILABLE_TOOLS[idx]["id"] == "SPADES"
                    for idx in tool_indices
                )
            except ImportError:
                self._logger.warning("Could not import AVAILABLE_TOOLS to check for QUAST/SPAdes")
        
        if fasta_files:
            if len(fasta_files) == 2 and has_quast and not has_spades:
                # Two FASTA files with QUAST but no SPAdes: first is assembly, second is reference
                formatted_parts.append(f"-assembly {fasta_files[0]}")
                formatted_parts.append(f"-fasta {fasta_files[1]}")
                self._logger.info(f"Detected 2 FASTA files for QUAST (no SPAdes): assembly={fasta_files[0]}, reference={fasta_files[1]}")
            elif len(fasta_files) == 1:
                formatted_parts.append(f"-fasta {fasta_files[0]}")
            else:
                # Multiple FASTA files - pass as list (for backward compatibility)
                fasta_list = ' '.join(fasta_files)
                formatted_parts.append(f"-fasta {fasta_list}")
        
        # If no FASTQ or FASTA files, use first file with default format
        if not formatted_parts:
            input_file = input_paths[0]
            formatted_parts.append(f"-fastq {input_file}")
        
        formatted_input = ' '.join(formatted_parts)
        self._logger.info(f"All files downloaded. Using input path: {formatted_input}")
        return formatted_input
    
    async def _run_pipeline_async(
        self,
        execution_id: int,
        job_id: int,
        user_id: int,
        tenant_container,
        input_path: str,
        tool_indices: List[int],
        output_dir: str
    ):
        """Run pipeline asynchronously and update status."""
        try:
            _ensure_emulator_dependencies()
            self._logger.info(f"Starting pipeline execution in tenant container {tenant_container.name}")
            self._logger.info(f"  - Job ID: {job_id}, Execution ID: {execution_id}")
            self._logger.info(f"  - Input path: {input_path}")
            self._logger.info(f"  - Tool indices: {tool_indices}")
            self._logger.info(f"  - Output directory: {output_dir}")
            
            # Run pipeline using emulator (blocking operation, run in thread pool)
            loop = asyncio.get_event_loop()
            self._logger.info("="*60)
            self._logger.info(f"EXECUTING PIPELINE IN TENANT CONTAINER")
            self._logger.info("="*60)
            self._logger.info(f"Container: {tenant_container.name}")
            self._logger.info(f"Input file: {input_path}")
            self._logger.info(f"Tool indices: {tool_indices}")
            self._logger.info("This may take several minutes depending on data size and tools...")
            self._logger.info("="*60)
            
            # Create a progress logger that also updates the execution record
            def progress_logger(msg):
                """Log progress and optionally update execution record."""
                self._logger.info(f"[PIPELINE] {msg}")
                # Could update execution record here with progress if needed
            
            result = await loop.run_in_executor(
                None,
                lambda: emulator_run_pipeline(tenant_container, input_path, tool_indices)
            )
            
            self._logger.info("="*60)
            self._logger.info(f"PIPELINE EXECUTION FINISHED")
            self._logger.info(f"Result length: {len(result) if result else 0} characters")
            self._logger.info("="*60)
            
            if result and isinstance(result, str) and ("error" in result.lower() or "failed" in result.lower()):
                # Pipeline failed
                self._logger.error(f"Pipeline execution failed for job {job_id}, execution {execution_id}")
                # Log full error (up to 10000 chars for debugging)
                error_preview = result[:10000] if len(result) > 10000 else result
                self._logger.error(f"Error output (first {len(error_preview)} chars):\n{error_preview}")
                if len(result) > 10000:
                    self._logger.error(f"... (truncated, total length: {len(result)} chars)")
                
                # Store full error in database (limit to 10000 chars to avoid DB issues)
                update_data = JobExecutionUpdate(
                    status=ExecutionStatus.FAILED,
                    error_message=result[:10000] if len(result) > 10000 else result,
                    completed_at=datetime.now()
                )
                update_job_execution(execution_id, update_data)
                from backend.api.models.job_model import JobUpdate
                update_job(job_id, user_id, JobUpdate(status=JobStatus.FAILED))
            else:
                # Pipeline completed successfully
                self._logger.info(f"Pipeline completed successfully for job {job_id}, execution {execution_id}")
                if result:
                    # Log first part of result for debugging
                    result_preview = result[:500] if len(result) > 500 else result
                    self._logger.info(f"Pipeline output preview: {result_preview}...")
                
                # Extract results path and pipeline run ID from pipeline output
                results_path = None
                pipeline_run_id = None
                if result and "Results saved to:" in result:
                    # Extract path from "Results saved to: /path/to/results"
                    import re
                    match = re.search(r'Results saved to:\s*(.+?)(?:\n|$)', result)
                    if match:
                        results_path = match.group(1).strip()
                        self._logger.info(f"Found results path: {results_path}")
                        
                        # Extract pipeline_run_* ID from path
                        pipeline_match = re.search(r'pipeline_run_(\d+)', results_path)
                        if pipeline_match:
                            pipeline_run_id = pipeline_match.group(1)
                            self._logger.info(f"Extracted pipeline run ID: {pipeline_run_id}")
                
                # Fallback: if we can't extract path, try to find the latest pipeline_run directory
                if not results_path:
                    self._logger.warning("Could not extract results path from pipeline output, trying fallback...")
                    # Find the latest pipeline_run directory in the tenant's home
                    find_result = tenant_container.exec_run(
                        ['find', f'/home/{tenant_container.name}', '-type', 'd', '-name', 'pipeline_run_*', '-maxdepth', '1'],
                        user='root'
                    )
                    if find_result.exit_code == 0:
                        pipeline_dirs = [line.strip() for line in find_result.output.decode().split('\n') if line.strip()]
                        if pipeline_dirs:
                            # Sort by name (which includes timestamp) and get the latest
                            pipeline_dirs.sort(reverse=True)
                            latest_pipeline_dir = pipeline_dirs[0]
                            results_path = os.path.join(latest_pipeline_dir, 'results')
                            # Extract pipeline run ID
                            pipeline_match = re.search(r'pipeline_run_(\d+)', latest_pipeline_dir)
                            if pipeline_match:
                                pipeline_run_id = pipeline_match.group(1)
                            self._logger.info(f"Using fallback results path: {results_path}")
                
                # Extract input filename from input_path (e.g., /data/input_1_SRR24940081.fastq -> SRR24940081)
                input_filename_base = None
                if input_path:
                    # Extract base filename without extension and without input_ prefix
                    import re
                    # Match pattern like input_1_SRR24940081.fastq or input_1_SRR24940081
                    filename_match = re.search(r'input_\d+_(.+?)(?:\.\w+)?$', input_path)
                    if filename_match:
                        input_filename_base = filename_match.group(1)
                        self._logger.info(f"Extracted input filename base: {input_filename_base}")
                
                # Collect and upload output files
                if results_path:
                    try:
                        self._collect_and_upload_outputs(
                            tenant_container, results_path, job_id, user_id, execution_id,
                            pipeline_run_id=pipeline_run_id,
                            input_filename_base=input_filename_base
                        )
                    except Exception as e:
                        self._logger.error(f"Failed to collect output files: {e}", exc_info=True)
                        # Don't fail the job if output collection fails
                else:
                    self._logger.warning("Could not determine results path, skipping output file collection")
                
                update_data = JobExecutionUpdate(
                    status=ExecutionStatus.COMPLETED,
                    completed_at=datetime.now()
                )
                update_job_execution(execution_id, update_data)
                from backend.api.models.job_model import JobUpdate
                update_job(job_id, user_id, JobUpdate(status=JobStatus.COMPLETED))
                prewarm_job_outputs_zip(job_id, user_id)
                
                self._logger.info(f"Job {job_id} marked as COMPLETED")
                
        except Exception as e:
            self._logger.error(f"Error running pipeline for job {job_id}, execution {execution_id}: {e}", exc_info=True)
            update_data = JobExecutionUpdate(
                status=ExecutionStatus.FAILED,
                error_message=str(e),
                completed_at=datetime.now()
            )
            update_job_execution(execution_id, update_data)
            from backend.api.models.job_model import JobUpdate
            update_job(job_id, user_id, JobUpdate(status=JobStatus.FAILED))
    
    def _collect_and_upload_outputs(
        self, tenant_container, results_path: str, job_id: int, user_id: int, execution_id: int,
        pipeline_run_id: Optional[str] = None, input_filename_base: Optional[str] = None
    ):
        """
        Collect output files from container and upload to MinIO.
        
        Args:
            tenant_container: Docker container object
            results_path: Path to results directory
            job_id: Job ID
            user_id: User ID
            execution_id: Execution ID
            pipeline_run_id: Optional pipeline run ID (e.g., '1766158518') for verification
            input_filename_base: Optional input filename base (e.g., 'SRR24940081') for filtering files
        """
        self._logger.info(f"Collecting output files from {results_path}...")
        if pipeline_run_id:
            self._logger.info(f"Using pipeline run ID: {pipeline_run_id}")
        if input_filename_base:
            self._logger.info(f"Using input filename base: {input_filename_base}")
        
        # List all files in results directory (recursively)
        # Use find to get all files
        find_result = tenant_container.exec_run(
            ['find', results_path, '-type', 'f'],
            user='root'
        )
        
        if find_result.exit_code != 0:
            self._logger.warning(f"Failed to list files in {results_path}: {find_result.output.decode()}")
            return
        
        all_file_paths = [line.strip() for line in find_result.output.decode().split('\n') if line.strip()]
        self._logger.info(f"Found {len(all_file_paths)} total files in {results_path}")
        
        # Filter files based on pipeline_run_id if provided
        # Note: We don't filter by input_filename_base for output files because
        # output files (like contigs.fasta, scaffolds.fasta) don't contain input filenames
        candidate_paths = []
        if pipeline_run_id:
            # Filter to files that match the pipeline run ID to ensure we're getting
            # files from the correct pipeline run
            for path in all_file_paths:
                if pipeline_run_id in path:
                    candidate_paths.append(path)
            self._logger.info(f"Filtered to {len(candidate_paths)} files matching pipeline_run_{pipeline_run_id}")
        else:
            # Use all files if no filtering criteria provided
            candidate_paths = all_file_paths
        
        # Filter to prioritize important files and exclude intermediate/config files
        # Important files: main outputs (contigs, scaffolds, reports, HTML)
        # Exclude: SPAdes config files, intermediate files, but keep QUAST/FastQC outputs
        important_patterns = [
            # SPAdes important outputs
            r'contigs\.fasta$',
            r'scaffolds\.fasta$',
            r'spades\.log$',  # SPAdes log is useful
            # QUAST important outputs (all QUAST files are important)
            r'/quast/',
            r'quast_report',
            r'report\.html$',
            r'report\.tsv$',
            r'contigs_reports/',
            # FastQC outputs
            r'/fastqc/',
            r'fastqc_report',
            r'fastqc_data\.txt$',
            r'\.zip$',  # FastQC zip files
            # GenomeScope2 outputs
            r'/genomescope2/',
            r'genomescope\.html$',
            r'plot\.png$',
            r'plot\.pdf$',
            # General important formats (but not from SPAdes configs)
            r'\.html$',
            r'\.tsv$',
            r'\.csv$',
            r'\.json$',
        ]
        
        exclude_patterns = [
            # SPAdes intermediate/config files (very specific patterns)
            r'configs_.*\.info$',  # Config info files
            r'params\.txt$',  # Params file
            r'\.lib_data$',  # Library data files
            r'simplified_contigs\.fasta$',  # Intermediate simplified contigs
            r'broken_scaffolds\.fasta$',  # Broken scaffolds (intermediate)
            r'\.paths$',  # Paths files (intermediate)
            r'k\d+_configs_.*\.info$',  # K-mer config info files
        ]
        
        import re
        file_paths = []
        excluded_count = 0
        
        for path in candidate_paths:
            filename = os.path.basename(path).lower()
            path_lower = path.lower()
            
            # Always include files from QUAST, FastQC, GenomeScope2 directories (all are important)
            # Also include files with QUAST/FastQC/GenomeScope2 prefixes (flattened naming)
            if any(tool in path_lower for tool in ['/quast/', '/fastqc/', '/genomescope2/', 'quast_out', 'fastqc_out', 'genomescope2_out']):
                file_paths.append(path)
                continue
            
            # For SPAdes files, be more selective
            if '/spades/' in path_lower or 'spades_out' in path_lower:
                # Include main SPAdes outputs
                if any(re.search(p, path_lower) for p in [r'contigs\.fasta$', r'scaffolds\.fasta$', r'spades\.log$']):
                    file_paths.append(path)
                    continue
                # Exclude SPAdes intermediate/config files
                if any(re.search(p, path_lower) for p in exclude_patterns):
                    excluded_count += 1
                    continue
                # For other SPAdes files, check if they're important
                if any(re.search(p, path_lower) for p in important_patterns):
                    file_paths.append(path)
                    continue
                # Exclude other SPAdes files (intermediate)
                excluded_count += 1
                continue
            
            # For files not in tool-specific directories, check if important
            is_important = any(re.search(p, path_lower) for p in important_patterns)
            should_exclude = any(re.search(p, path_lower) for p in exclude_patterns)
            
            if is_important and not should_exclude:
                file_paths.append(path)
            elif should_exclude:
                excluded_count += 1
        
        self._logger.info(f"Filtered files: {len(file_paths)} important files, {excluded_count} intermediate/config files excluded")
        
        # Log which tool directories we found files from
        tool_dirs = set()
        for path in file_paths[:20]:  # Check first 20 files
            # Extract tool directory (e.g., results/SPAdes/ or results/QUAST/)
            parts = path.split('/')
            for i, part in enumerate(parts):
                if part.upper() in ['SPADES', 'QUAST', 'FASTQC', 'GENOMESCOPE2']:
                    tool_dirs.add(part)
                    break
        if tool_dirs:
            self._logger.info(f"Found output files from tools: {', '.join(sorted(tool_dirs))}")
        
        if not file_paths:
            self._logger.warning(f"No output files found in {results_path}")
            if pipeline_run_id or input_filename_base:
                self._logger.warning(f"Filter criteria - pipeline_run_id: {pipeline_run_id}, input_filename_base: {input_filename_base}")
            # Try to list directory contents for debugging
            ls_result = tenant_container.exec_run(
                ['ls', '-laR', results_path],
                user='root'
            )
            if ls_result.exit_code == 0:
                self._logger.info(f"Directory listing:\n{ls_result.output.decode()}")
            return
        
        # Log first few file paths for debugging
        for i, path in enumerate(file_paths[:5]):
            self._logger.info(f"  Found file {i+1}: {path}")
        if len(file_paths) > 5:
            self._logger.info(f"  ... and {len(file_paths) - 5} more files")
        
        # Create temp directory for collecting files
        temp_dir = tempfile.mkdtemp(prefix='cassie_outputs_')
        
        try:
            minio_client = get_minio_client()
            uploaded_count = 0
            
            for container_file_path in file_paths:
                try:
                    # Get filename from path
                    filename = os.path.basename(container_file_path)
                    # Preserve directory structure in filename
                    rel_path = os.path.relpath(container_file_path, results_path)
                    safe_filename = rel_path.replace('/', '_').replace('\\', '_')
                    
                    # Copy file from container to temp directory
                    # Ensure parent directory exists
                    local_file_path = os.path.join(temp_dir, safe_filename)
                    os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
                    
                    self._logger.info(f"Copying {container_file_path} to {local_file_path}...")
                    try:
                        self._copy_file_from_container(tenant_container, container_file_path, local_file_path)
                    except Exception as copy_error:
                        self._logger.warning(f"Failed to copy {container_file_path}: {copy_error}")
                        continue
                    
                    # Verify file exists and has content
                    if not os.path.exists(local_file_path):
                        self._logger.warning(f"File {local_file_path} was not created after container copy")
                        continue
                    
                    file_size = os.path.getsize(local_file_path)
                    if file_size == 0:
                        self._logger.warning(f"File {local_file_path} is empty (0 bytes)")
                        continue
                    
                    self._logger.info(f"Successfully copied {container_file_path} ({file_size} bytes)")
                    
                    # Determine file type and format
                    file_type = FileType.OUTPUT
                    file_format = None
                    if filename.endswith('.zip'):
                        file_format = 'zip'
                    elif filename.endswith('.html'):
                        file_format = 'html'
                    elif filename.endswith('.txt'):
                        file_format = 'txt'
                    elif filename.endswith('.fastq') or filename.endswith('.fq'):
                        file_format = 'fastq'
                    elif filename.endswith('.fasta') or filename.endswith('.fa'):
                        file_format = 'fasta'
                    
                    # Upload to MinIO/S3 using the proper upload_file method.
                    # This ensures the shared bucket exists, applies the per-user prefix,
                    # and keeps the logical s3_key format used across the app.
                    s3_key = f"jobs/{job_id}/outputs/{safe_filename}"
                    self._logger.info(f"Uploading {safe_filename} to shared storage for user {user_id} (s3_key: {s3_key})...")
                    
                    # Use the MinIO client's upload_file method which handles bucket creation
                    # and storage prefixing automatically.
                    upload_result = minio_client.upload_file(
                        user_id=user_id,
                        local_path=local_file_path,
                        s3_key=s3_key,
                        username=None
                    )
                    
                    self._logger.info(
                        f"✓ Uploaded {safe_filename} to storage bucket '{upload_result['bucket']}': "
                        f"{upload_result['size']} bytes, checksum: {upload_result['checksum']}"
                    )
                    
                    # Create file record
                    from datetime import datetime
                    file_data = FileCreate(
                        job_id=job_id,
                        filename=safe_filename,
                        s3_key=s3_key,
                        file_type=file_type,
                        file_format=file_format,
                        size_bytes=upload_result['size'],
                        checksum=upload_result['checksum'],
                        uploaded_at=datetime.now()
                    )
                    
                    self._logger.info(f"Creating file record for job {job_id}: {safe_filename} (type: {file_type.value})")
                    file_record = create_file_record(file_data)
                    self._logger.info(f"✓ Created file record: id={file_record.id}, job_id={file_record.job_id}, file_type={file_record.file_type.value}, filename={file_record.filename}")
                    uploaded_count += 1
                    
                except Exception as e:
                    self._logger.error(f"Error processing output file {container_file_path}: {e}", exc_info=True)
                    continue
            
            self._logger.info(f"Successfully uploaded {uploaded_count}/{len(file_paths)} output files")
            
            # Verify files were created in database and are accessible in user's bucket
            if uploaded_count > 0:
                from backend.api.services.storage_service import get_files_by_user
                verify_files = get_files_by_user(
                    user_id=user_id,
                    job_id=job_id,
                    file_type=FileType.OUTPUT,
                    limit=100
                )
                self._logger.info(f"Verified: Found {len(verify_files)} output files in database for job {job_id}")
                
                # Verify files exist in user's MinIO bucket
                bucket_name = minio_client._get_bucket_name(user_id, None)
                self._logger.info(f"Verifying files exist in user {user_id}'s bucket: {bucket_name}")
                
                for vf in verify_files:
                    # Check if file exists in user's bucket
                    file_exists = minio_client.file_exists(
                        user_id=user_id,
                        s3_key=vf.s3_key,
                        username=None
                    )
                    if file_exists:
                        self._logger.info(
                            f"  ✓ File {vf.id}: {vf.filename} (type: {vf.file_type.value}, "
                            f"bucket: {bucket_name}, s3_key: {vf.s3_key})"
                        )
                    else:
                        self._logger.warning(
                            f"  ✗ File {vf.id}: {vf.filename} NOT FOUND in bucket {bucket_name} "
                            f"(s3_key: {vf.s3_key})"
                        )
            
        finally:
            # Clean up temp directory
            try:
                shutil.rmtree(temp_dir)
            except Exception as e:
                self._logger.warning(f"Failed to clean up temp directory {temp_dir}: {e}")


# Singleton instance
_emulator_runner_instance: Optional[EmulatorPipelineRunner] = None


def get_emulator_pipeline_runner() -> EmulatorPipelineRunner:
    """Get or create singleton emulator pipeline runner instance."""
    global _emulator_runner_instance
    if _emulator_runner_instance is None:
        _emulator_runner_instance = EmulatorPipelineRunner()
    return _emulator_runner_instance
