"""
Job execution service for managing pipeline executions.

This service handles:
- Creating job execution records
- Updating execution status
- Tracking pipeline progress
"""

import json
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import contextmanager
from backend.api.database.db_init import get_db_connection
from backend.api.models.job_model import (
    JobExecutionCreate,
    JobExecutionUpdate,
    JobExecutionInDB,
    ExecutionStatus
)
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


def create_job_execution(execution_data: JobExecutionCreate) -> JobExecutionInDB:
    """
    Create a new job execution record.
    
    Args:
        execution_data: Job execution creation data
        
    Returns:
        JobExecutionInDB: Created execution record
    """
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Convert tool_versions and parameters_used to JSONB
            tool_versions_json = json.dumps(execution_data.tool_versions) if execution_data.tool_versions else None
            parameters_json = json.dumps(execution_data.parameters_used) if execution_data.parameters_used else None
            
            cur.execute("""
                INSERT INTO job_executions (
                    job_id, execution_number, status, nextflow_run_id,
                    work_dir, output_dir, process_id,
                    tool_versions, parameters_used, error_message,
                    started_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING id, job_id, execution_number, status, nextflow_run_id,
                          work_dir, output_dir, process_id, tool_versions,
                          parameters_used, error_message, started_at, completed_at, created_at
            """, (
                execution_data.job_id,
                execution_data.execution_number,
                execution_data.status.value,
                execution_data.nextflow_run_id,
                execution_data.work_dir,
                execution_data.output_dir,
                execution_data.process_id,
                tool_versions_json,
                parameters_json,
                execution_data.error_message,
                execution_data.started_at or datetime.now()
            ))
            
            row = cur.fetchone()
            conn.commit()
            
            # Parse JSONB fields
            tool_versions = row[8] if row[8] else None
            if isinstance(tool_versions, str):
                tool_versions = json.loads(tool_versions)
            
            parameters_used = row[9] if row[9] else None
            if isinstance(parameters_used, str):
                parameters_used = json.loads(parameters_used)
            
            return JobExecutionInDB(
                id=row[0],
                job_id=row[1],
                execution_number=row[2],
                status=ExecutionStatus(row[3]),
                nextflow_run_id=row[4],
                work_dir=row[5],
                output_dir=row[6],
                process_id=row[7],
                tool_versions=tool_versions,
                parameters_used=parameters_used,
                error_message=row[10],
                started_at=row[11],
                completed_at=row[12],
                created_at=row[13]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error creating job execution: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_job_execution_by_id(execution_id: int) -> Optional[JobExecutionInDB]:
    """Get job execution by ID."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, job_id, execution_number, status, nextflow_run_id,
                       work_dir, output_dir, process_id, tool_versions,
                       parameters_used, error_message, started_at, completed_at, created_at
                FROM job_executions
                WHERE id = %s
            """, (execution_id,))
            
            row = cur.fetchone()
            if not row:
                return None
            
            # Parse JSONB fields
            tool_versions = row[8] if row[8] else None
            if isinstance(tool_versions, str):
                tool_versions = json.loads(tool_versions)
            
            parameters_used = row[9] if row[9] else None
            if isinstance(parameters_used, str):
                parameters_used = json.loads(parameters_used)
            
            return JobExecutionInDB(
                id=row[0],
                job_id=row[1],
                execution_number=row[2],
                status=ExecutionStatus(row[3]),
                nextflow_run_id=row[4],
                work_dir=row[5],
                output_dir=row[6],
                process_id=row[7],
                tool_versions=tool_versions,
                parameters_used=parameters_used,
                error_message=row[10],
                started_at=row[11],
                completed_at=row[12],
                created_at=row[13]
            )
        finally:
            cur.close()


def get_executions_by_job(job_id: int) -> List[JobExecutionInDB]:
    """Get all executions for a job."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, job_id, execution_number, status, nextflow_run_id,
                       work_dir, output_dir, process_id, tool_versions,
                       parameters_used, error_message, started_at, completed_at, created_at
                FROM job_executions
                WHERE job_id = %s
                ORDER BY execution_number DESC
            """, (job_id,))
            
            executions = []
            for row in cur.fetchall():
                # Parse JSONB fields
                tool_versions = row[8] if row[8] else None
                if isinstance(tool_versions, str):
                    tool_versions = json.loads(tool_versions)
                
                parameters_used = row[9] if row[9] else None
                if isinstance(parameters_used, str):
                    parameters_used = json.loads(parameters_used)
                
                executions.append(JobExecutionInDB(
                    id=row[0],
                    job_id=row[1],
                    execution_number=row[2],
                    status=ExecutionStatus(row[3]),
                    nextflow_run_id=row[4],
                    work_dir=row[5],
                    output_dir=row[6],
                    process_id=row[7],
                    tool_versions=tool_versions,
                    parameters_used=parameters_used,
                    error_message=row[10],
                    started_at=row[11],
                    completed_at=row[12],
                    created_at=row[13]
                ))
            
            return executions
        finally:
            cur.close()


def update_job_execution(execution_id: int, update_data: JobExecutionUpdate) -> Optional[JobExecutionInDB]:
    """Update job execution record."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            # Build update query dynamically
            updates = []
            params = []
            
            if update_data.status is not None:
                updates.append("status = %s")
                params.append(update_data.status.value)
            
            if update_data.nextflow_run_id is not None:
                updates.append("nextflow_run_id = %s")
                params.append(update_data.nextflow_run_id)
            
            if update_data.work_dir is not None:
                updates.append("work_dir = %s")
                params.append(update_data.work_dir)
            
            if update_data.output_dir is not None:
                updates.append("output_dir = %s")
                params.append(update_data.output_dir)
            
            if update_data.process_id is not None:
                updates.append("process_id = %s")
                params.append(update_data.process_id)
            
            if update_data.tool_versions is not None:
                updates.append("tool_versions = %s")
                params.append(json.dumps(update_data.tool_versions))
            
            if update_data.parameters_used is not None:
                updates.append("parameters_used = %s")
                params.append(json.dumps(update_data.parameters_used))
            
            if update_data.error_message is not None:
                updates.append("error_message = %s")
                params.append(update_data.error_message)
            
            if update_data.completed_at is not None:
                updates.append("completed_at = %s")
                params.append(update_data.completed_at)
            
            if not updates:
                # No updates, just return current record
                return get_job_execution_by_id(execution_id)
            
            params.append(execution_id)
            
            cur.execute(f"""
                UPDATE job_executions
                SET {', '.join(updates)}
                WHERE id = %s
                RETURNING id, job_id, execution_number, status, nextflow_run_id,
                          work_dir, output_dir, process_id, tool_versions,
                          parameters_used, error_message, started_at, completed_at, created_at
            """, params)
            
            row = cur.fetchone()
            if not row:
                return None
            
            conn.commit()
            
            # Parse JSONB fields
            tool_versions = row[8] if row[8] else None
            if isinstance(tool_versions, str):
                tool_versions = json.loads(tool_versions)
            
            parameters_used = row[9] if row[9] else None
            if isinstance(parameters_used, str):
                parameters_used = json.loads(parameters_used)
            
            return JobExecutionInDB(
                id=row[0],
                job_id=row[1],
                execution_number=row[2],
                status=ExecutionStatus(row[3]),
                nextflow_run_id=row[4],
                work_dir=row[5],
                output_dir=row[6],
                process_id=row[7],
                tool_versions=tool_versions,
                parameters_used=parameters_used,
                error_message=row[10],
                started_at=row[11],
                completed_at=row[12],
                created_at=row[13]
            )
            
        except Exception as e:
            conn.rollback()
            logger.error(f"Error updating job execution: {e}", exc_info=True)
            raise
        finally:
            cur.close()


def get_running_executions() -> List[JobExecutionInDB]:
    """Get all running job executions."""
    with get_db_connection() as conn:
        cur = conn.cursor()
        
        try:
            cur.execute("""
                SELECT id, job_id, execution_number, status, nextflow_run_id,
                       work_dir, output_dir, process_id, tool_versions,
                       parameters_used, error_message, started_at, completed_at, created_at
                FROM job_executions
                WHERE status = 'running'
                ORDER BY started_at ASC
            """)
            
            executions = []
            for row in cur.fetchall():
                # Parse JSONB fields
                tool_versions = row[8] if row[8] else None
                if isinstance(tool_versions, str):
                    tool_versions = json.loads(tool_versions)
                
                parameters_used = row[9] if row[9] else None
                if isinstance(parameters_used, str):
                    parameters_used = json.loads(parameters_used)
                
                executions.append(JobExecutionInDB(
                    id=row[0],
                    job_id=row[1],
                    execution_number=row[2],
                    status=ExecutionStatus(row[3]),
                    nextflow_run_id=row[4],
                    work_dir=row[5],
                    output_dir=row[6],
                    process_id=row[7],
                    tool_versions=tool_versions,
                    parameters_used=parameters_used,
                    error_message=row[10],
                    started_at=row[11],
                    completed_at=row[12],
                    created_at=row[13]
                ))
            
            return executions
        finally:
            cur.close()

