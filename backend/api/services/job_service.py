"""
Job service for database operations.

This module provides database operations for job management.
"""

import json
from typing import Optional, List
from contextlib import contextmanager
from backend.api.database.db_init import get_db_connection
from backend.api.models.job_model import JobInDB, JobCreate, JobUpdate, JobResponse, JobStatus, CloudProvider
from backend.api.utils.logger import get_logger
from tool_registry import get_tool_by_index

logger = get_logger(__name__)


def create_job(user_id: int, job_data: JobCreate) -> JobInDB:
    """
    Create a new job in the database.
    
    Args:
        user_id: ID of the user creating the job
        job_data: Job creation data
        
    Returns:
        JobInDB: Created job with database fields
        
    Raises:
        ValueError: If workflow_id doesn't exist or tool_indices are invalid
    """
    # Handle pipeline_id: convert to tool_indices
    logger.info(f"[JOB SERVICE] Creating job with pipeline_id={job_data.pipeline_id}, tool_indices={job_data.tool_indices}")
    tool_indices = job_data.tool_indices

    def selected_tool_ids(indices: Optional[List[int]]) -> set[str]:
        resolved_ids = set()
        for index in indices or []:
            tool = get_tool_by_index(index)
            if tool:
                resolved_ids.add(tool["id"])
        return resolved_ids

    if job_data.pipeline_id:
        if tool_indices:
            raise ValueError("Cannot specify both pipeline_id and tool_indices. Use one or the other.")
        
        # Load pipeline and convert to tool_indices
        from backend.api.services.pipeline_service import get_pipeline_by_id
        from backend.api.services.pipeline_converter import convert_pipeline_to_tool_indices
        
        pipeline = get_pipeline_by_id(job_data.pipeline_id, user_id)
        if not pipeline:
            raise ValueError(f"Pipeline {job_data.pipeline_id} not found or does not belong to user")
        
        try:
            tool_indices = convert_pipeline_to_tool_indices(pipeline)
            logger.info(f"Converted pipeline {job_data.pipeline_id} to tool_indices: {tool_indices}")
        except Exception as e:
            raise ValueError(f"Failed to convert pipeline to tool indices: {str(e)}")
    
    # If tool_indices provided (either directly or from pipeline), create workflow dynamically
    workflow_id = job_data.workflow_id
    if tool_indices:
        # Check input files to determine capabilities
        has_reference = False
        has_assembly = False
        has_paired_end = False
        fastq_count = 0
        fasta_count = 0
        
        if job_data.input_file_ids:
            from backend.api.services.storage_service import get_file_by_id
            for file_id in job_data.input_file_ids:
                try:
                    file_record = get_file_by_id(file_id, user_id=user_id)
                    if file_record:
                        filename_lower = file_record.filename.lower()
                        if filename_lower.endswith(('.fasta', '.fa', '.fna')):
                            fasta_count += 1
                            logger.info(f"Detected FASTA file: {file_record.filename}")
                        elif filename_lower.endswith(('.fastq', '.fq')):
                            fastq_count += 1
                except Exception as e:
                    logger.warning(f"Could not check file {file_id}: {e}")
        
        # If there are 2 FASTA files, one is assembly and one is reference (for QUAST)
        # If there's 1 FASTA file and QUAST is selected, assume it's a reference (assembly comes from SPAdes)
        # If there's 1 FASTA file and QUAST is selected but SPAdes is NOT, we need to detect which it is
        # For now, if 2 FASTA files: both assembly and reference are present
        if fasta_count >= 2:
            has_reference = True
            has_assembly = True
            logger.info(f"Detected {fasta_count} FASTA files: assuming 1 assembly + 1 reference for QUAST")
        elif fasta_count == 1:
            # Check if SPAdes is in tool_indices - if not, the FASTA might be an assembly
            has_spades = False
            if tool_indices:
                has_spades = "SPADES" in selected_tool_ids(tool_indices)
            
            if has_spades:
                # SPAdes will generate assembly, so this FASTA is the reference
                has_reference = True
                logger.info(f"Detected reference genome file (SPAdes will generate assembly)")
            else:
                # No SPAdes, so this FASTA could be an assembly, but we still need a reference
                # For QUAST to work without SPAdes, we need 2 FASTA files (1 assembly + 1 reference)
                # So if only 1 FASTA and no SPAdes, we can't determine if it's assembly or reference
                # We'll assume it's a reference for now, but QUAST will still require SPAdes or another assembly
                has_reference = True
                logger.info(f"Detected 1 FASTA file (no SPAdes selected): assuming reference. QUAST requires 2 FASTA files (assembly + reference) when SPAdes is not selected.")
        
        # SPAdes requires paired-end reads (2 FASTQ files)
        has_paired_end = fastq_count >= 2
        if fastq_count == 1:
            logger.info(f"Detected single-end reads (1 FASTQ file). SPAdes will be filtered out if selected.")
        elif fastq_count >= 2:
            logger.info(f"Detected paired-end reads ({fastq_count} FASTQ files). SPAdes can run.")
        
        # Check if SPAdes is in tool_indices (to determine if FASTA is assembly or reference)
        has_spades = False
        if tool_indices:
            has_spades = "SPADES" in selected_tool_ids(tool_indices)
        
        from backend.api.services.workflow_service import create_workflow_from_tools
        workflow_id = create_workflow_from_tools(
            tool_indices=tool_indices,
            user_id=user_id,
            workflow_name=f"{job_data.name} Workflow",  # Use job name to make workflow name unique per job
            has_reference_file=has_reference,
            has_paired_end_reads=has_paired_end,
            has_assembly_file=has_assembly
        )
        logger.info(f"Created workflow {workflow_id} dynamically from tool indices: {tool_indices} (has_reference: {has_reference}, has_assembly: {has_assembly}, has_paired_end: {has_paired_end})")
    elif not workflow_id:
        raise ValueError("Either workflow_id or tool_indices must be provided")
    
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Verify workflow exists
            cur.execute("SELECT id FROM workflows WHERE id = %s", (workflow_id,))
            if not cur.fetchone():
                raise ValueError(f"Workflow with id {workflow_id} not found")
            
            # Verify pipeline_config exists if provided
            if job_data.pipeline_config_id:
                cur.execute("SELECT id FROM pipeline_configs WHERE id = %s", (job_data.pipeline_config_id,))
                if not cur.fetchone():
                    raise ValueError(f"Pipeline config with id {job_data.pipeline_config_id} not found")
            
            # Convert data_types list to JSONB
            data_types_json = json.dumps(job_data.data_types) if job_data.data_types else None
            
            # Insert job
            logger.info(f"[JOB SERVICE] Inserting job with pipeline_id={job_data.pipeline_id}, workflow_id={workflow_id}")
            cur.execute("""
                INSERT INTO jobs (user_id, name, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
            """, (
                user_id,
                job_data.name,
                workflow_id,  # Use dynamically created or provided workflow_id
                job_data.pipeline_config_id,
                job_data.pipeline_id,  # Preserve pipeline_id even when converting to tool_indices
                job_data.assembler,
                data_types_json,
                job_data.cloud_provider.value if job_data.cloud_provider else None,
                job_data.vm_name,
                JobStatus.PENDING.value
            ))
            
            row = cur.fetchone()
            conn.commit()
            
            # Parse data_types from JSONB (psycopg2 already converts JSONB to Python objects)
            # Column order: id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
            data_types = row[8] if row[8] else None
            if isinstance(data_types, str):
                data_types = json.loads(data_types)
            
            # Handle cloud_provider - convert string to enum if present
            cloud_provider_value = None
            if row[9]:
                try:
                    cloud_provider_value = CloudProvider(row[9])
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid cloud_provider value: {row[9]}")
                    cloud_provider_value = None
            
            return JobInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                status=JobStatus(row[3]),
                workflow_id=row[4],
                pipeline_config_id=row[5],
                pipeline_id=row[6],
                assembler=row[7] if row[7] else None,
                data_types=data_types,
                cloud_provider=cloud_provider_value,
                vm_name=row[10],
                created_at=row[11],
                updated_at=row[12]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating job: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_job_by_id(job_id: int, user_id: Optional[int] = None) -> Optional[JobInDB]:
    """
    Get a job by ID, optionally filtered by user_id.
    
    Args:
        job_id: Job ID to search for
        user_id: Optional user ID to verify ownership
        
    Returns:
        JobInDB: Job if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if user_id:
                cur.execute("""
                    SELECT id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
                    FROM jobs
                    WHERE id = %s AND user_id = %s
                """, (job_id, user_id))
            else:
                cur.execute("""
                    SELECT id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
                    FROM jobs
                    WHERE id = %s
                """, (job_id,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            # Parse data_types from JSONB (psycopg2 already converts JSONB to Python objects)
            # Column order: id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
            data_types = row[8] if row[8] else None
            if isinstance(data_types, str):
                data_types = json.loads(data_types)
            
            # Handle cloud_provider - convert string to enum if present
            cloud_provider_value = None
            if row[9]:
                try:
                    cloud_provider_value = CloudProvider(row[9])
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid cloud_provider value: {row[9]}")
                    cloud_provider_value = None
            
            return JobInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                status=JobStatus(row[3]),
                workflow_id=row[4],
                pipeline_config_id=row[5],
                pipeline_id=row[6],
                assembler=row[7] if row[7] else None,
                data_types=data_types,
                cloud_provider=cloud_provider_value,
                vm_name=row[10],
                created_at=row[11],
                updated_at=row[12]
            )
        finally:
            cur.close()


def get_jobs_by_user(user_id: int, status: Optional[JobStatus] = None, limit: int = 100, offset: int = 0) -> List[JobInDB]:
    """
    Get all jobs for a user, optionally filtered by status.
    
    Args:
        user_id: User ID to filter by
        status: Optional status filter
        limit: Maximum number of jobs to return
        offset: Number of jobs to skip
        
    Returns:
        List[JobInDB]: List of jobs
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if status:
                cur.execute("""
                    SELECT id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
                    FROM jobs
                    WHERE user_id = %s AND status = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (user_id, status.value, limit, offset))
            else:
                cur.execute("""
                    SELECT id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
                    FROM jobs
                    WHERE user_id = %s
                    ORDER BY created_at DESC
                    LIMIT %s OFFSET %s
                """, (user_id, limit, offset))
            
            rows = cur.fetchall()
            jobs = []
            
            for row in rows:
                # Parse data_types from JSONB (psycopg2 already converts JSONB to Python objects)
                # Column order: id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
                data_types = row[8] if row[8] else None
                # If it's a string, parse it; otherwise it's already a Python object
                if isinstance(data_types, str):
                    data_types = json.loads(data_types)
                
                # Handle cloud_provider - convert string to enum if present
                cloud_provider_value = None
                if row[9]:
                    try:
                        cloud_provider_value = CloudProvider(row[9])
                    except (ValueError, AttributeError):
                        logger.warning(f"Invalid cloud_provider value: {row[9]}")
                        cloud_provider_value = None
                
                jobs.append(JobInDB(
                    id=row[0],
                    user_id=row[1],
                    name=row[2],
                    status=JobStatus(row[3]),
                    workflow_id=row[4],
                    pipeline_config_id=row[5],
                    pipeline_id=row[6],
                    assembler=row[7] if row[7] else None,
                    data_types=data_types,
                    cloud_provider=cloud_provider_value,
                    vm_name=row[10],
                    created_at=row[11],
                    updated_at=row[12]
                ))
            
            return jobs
        finally:
            cur.close()


def update_job(job_id: int, user_id: int, job_update: JobUpdate) -> Optional[JobInDB]:
    """
    Update a job.
    
    Args:
        job_id: Job ID to update
        user_id: User ID to verify ownership
        job_update: Job update data
        
    Returns:
        JobInDB: Updated job if found and accessible, None otherwise
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Build update query dynamically based on provided fields
            updates = []
            values = []
            
            if job_update.name is not None:
                updates.append("name = %s")
                values.append(job_update.name)
            
            if job_update.status is not None:
                updates.append("status = %s")
                values.append(job_update.status.value)
            
            if job_update.assembler is not None:
                updates.append("assembler = %s")
                values.append(job_update.assembler)
            
            if job_update.data_types is not None:
                updates.append("data_types = %s")
                values.append(json.dumps(job_update.data_types))
            
            if job_update.cloud_provider is not None:
                updates.append("cloud_provider = %s")
                values.append(job_update.cloud_provider.value)
            
            if job_update.vm_name is not None:
                updates.append("vm_name = %s")
                values.append(job_update.vm_name)
            
            if not updates:
                # No updates provided, just return the existing job
                return get_job_by_id(job_id, user_id)
            
            # Add updated_at
            updates.append("updated_at = CURRENT_TIMESTAMP")
            
            # Add WHERE clause
            values.extend([job_id, user_id])
            
            query = f"""
                UPDATE jobs
                SET {', '.join(updates)}
                WHERE id = %s AND user_id = %s
                RETURNING id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
            """
            
            cur.execute(query, values)
            row = cur.fetchone()
            
            if not row:
                return None
            
            conn.commit()
            
            # Parse data_types from JSONB (psycopg2 already converts JSONB to Python objects)
            # Column order: id, user_id, name, status, workflow_id, pipeline_config_id, pipeline_id, assembler, data_types, cloud_provider, vm_name, created_at, updated_at
            data_types = row[8] if row[8] else None
            if isinstance(data_types, str):
                data_types = json.loads(data_types)
            
            # Handle cloud_provider - convert string to enum if present
            cloud_provider_value = None
            if row[9]:
                try:
                    cloud_provider_value = CloudProvider(row[9])
                except (ValueError, AttributeError):
                    logger.warning(f"Invalid cloud_provider value: {row[9]}")
                    cloud_provider_value = None
            
            return JobInDB(
                id=row[0],
                user_id=row[1],
                name=row[2],
                status=JobStatus(row[3]),
                workflow_id=row[4],
                pipeline_config_id=row[5],
                pipeline_id=row[6],
                assembler=row[7] if row[7] else None,
                data_types=data_types,
                cloud_provider=cloud_provider_value,
                vm_name=row[10],
                created_at=row[11],
                updated_at=row[12]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating job: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def delete_job(job_id: int, user_id: int) -> bool:
    """
    Delete a job.
    
    Args:
        job_id: Job ID to delete
        user_id: User ID to verify ownership
        
    Returns:
        bool: True if job was deleted, False if not found or not accessible
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("DELETE FROM jobs WHERE id = %s AND user_id = %s", (job_id, user_id))
            deleted = cur.rowcount > 0
            conn.commit()
            return deleted
        except Exception as e:
            conn.rollback()
            logger.error(f"Error deleting job: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def count_jobs_by_user(user_id: int, status: Optional[JobStatus] = None) -> int:
    """
    Count jobs for a user, optionally filtered by status.
    
    Args:
        user_id: User ID to filter by
        status: Optional status filter
        
    Returns:
        int: Number of jobs
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            if status:
                cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id = %s AND status = %s", (user_id, status.value))
            else:
                cur.execute("SELECT COUNT(*) FROM jobs WHERE user_id = %s", (user_id,))
            
            return cur.fetchone()[0]
        finally:
            cur.close()
