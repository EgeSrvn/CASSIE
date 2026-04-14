"""
Mock pipeline runner for demo purposes.

This service simulates pipeline execution without requiring Nextflow.
It's useful for frontend development and demos.

For production, replace this with actual NextflowRunner integration.
"""

import os
import uuid
import time
import asyncio
from typing import Dict, Any, Optional
from datetime import datetime, timedelta
from backend.api.services.job_execution_service import (
    create_job_execution,
    update_job_execution,
    get_job_execution_by_id
)
from backend.api.services.job_archive_service import prewarm_job_outputs_zip
from backend.api.services.job_service import update_job
from backend.api.models.job_model import (
    JobExecutionCreate,
    JobExecutionUpdate,
    ExecutionStatus,
    JobStatus
)
from backend.api.utils.logger import get_logger

logger = get_logger(__name__)


class MockPipelineRunner:
    """
    Mock pipeline runner that simulates pipeline execution.
    
    This simulates:
    - Pipeline starting (status: running)
    - Pipeline progress (simulated delay)
    - Pipeline completion (status: completed)
    - Output file generation (mock files)
    """
    
    def __init__(self):
        """Initialize mock pipeline runner."""
        self._running_tasks: Dict[int, asyncio.Task] = {}
    
    async def start_pipeline(
        self,
        job_id: int,
        workflow_id: int,
        input_files: list,
        execution_number: int = 1
    ) -> Dict[str, Any]:
        """
        Start a mock pipeline execution.
        
        Args:
            job_id: Job ID
            workflow_id: Workflow ID
            input_files: List of input file IDs
            execution_number: Execution attempt number
            
        Returns:
            dict: Execution details with execution_id, nextflow_run_id, etc.
        """
        # Generate mock execution details
        nextflow_run_id = f"mock-{uuid.uuid4().hex[:12]}"
        work_dir = f"./work/job-{job_id}/exec-{execution_number}"
        output_dir = f"./output/job-{job_id}/exec-{execution_number}"
        process_id = os.getpid()  # Mock process ID
        
        # Create job execution record
        execution_data = JobExecutionCreate(
            job_id=job_id,
            execution_number=execution_number,
            status=ExecutionStatus.RUNNING,
            nextflow_run_id=nextflow_run_id,
            work_dir=work_dir,
            output_dir=output_dir,
            process_id=process_id,
            tool_versions={"fastqc": "0.12.1"},  # Mock tool versions
            parameters_used={"input_files": input_files, "workflow_id": workflow_id},
            started_at=datetime.now()
        )
        
        execution = create_job_execution(execution_data)
        
        # Update job status to running
        from backend.api.models.job_model import JobUpdate
        update_job(job_id, 0, JobUpdate(status=JobStatus.RUNNING))  # user_id=0 for system
        
        logger.info(f"Started mock pipeline execution for job {job_id}, execution {execution.id}")
        
        # Start background task to simulate pipeline completion
        task = asyncio.create_task(self._simulate_pipeline_completion(execution.id, job_id))
        self._running_tasks[execution.id] = task
        
        return {
            'execution_id': execution.id,
            'nextflow_run_id': nextflow_run_id,
            'work_dir': work_dir,
            'output_dir': output_dir,
            'process_id': process_id,
            'started_at': execution.started_at.isoformat() if execution.started_at else None
        }
    
    async def _simulate_pipeline_completion(self, execution_id: int, job_id: int):
        """
        Simulate pipeline execution and completion.
        
        This runs in the background and updates the execution status after a delay.
        """
        try:
            # Simulate pipeline running time (10-30 seconds for demo)
            import random
            delay = random.uniform(10, 30)
            
            logger.info(f"Simulating pipeline execution for job {job_id}, execution {execution_id} (will complete in {delay:.1f}s)")
            
            # Wait for simulated execution time
            await asyncio.sleep(delay)
            
            # Update execution to completed
            update_data = JobExecutionUpdate(
                status=ExecutionStatus.COMPLETED,
                completed_at=datetime.now()
            )
            
            updated_execution = update_job_execution(execution_id, update_data)
            
            if updated_execution:
                # Update job status to completed
                from backend.api.models.job_model import JobUpdate
                update_job(job_id, 0, JobUpdate(status=JobStatus.COMPLETED))  # user_id=0 for system
                prewarm_job_outputs_zip(job_id, 0)
                
                logger.info(f"Mock pipeline completed for job {job_id}, execution {execution_id}")
            else:
                logger.warning(f"Could not update execution {execution_id} to completed")
                
        except Exception as e:
            logger.error(f"Error simulating pipeline completion: {e}", exc_info=True)
            
            # Mark as failed
            try:
                update_data = JobExecutionUpdate(
                    status=ExecutionStatus.FAILED,
                    error_message=f"Mock pipeline simulation error: {str(e)}",
                    completed_at=datetime.now()
                )
                update_job_execution(execution_id, update_data)
                
                # Update job status to failed
                from backend.api.models.job_model import JobUpdate
                update_job(job_id, 0, JobUpdate(status=JobStatus.FAILED))
            except Exception as update_error:
                logger.error(f"Error updating execution to failed: {update_error}")
        finally:
            # Remove from running tasks
            if execution_id in self._running_tasks:
                del self._running_tasks[execution_id]
    
    def cancel_execution(self, execution_id: int) -> bool:
        """
        Cancel a running execution.
        
        Args:
            execution_id: Execution ID to cancel
            
        Returns:
            bool: True if cancelled successfully
        """
        try:
            execution = get_job_execution_by_id(execution_id)
            if not execution:
                return False
            
            if execution.status != ExecutionStatus.RUNNING:
                return False
            
            # Cancel the background task
            if execution_id in self._running_tasks:
                task = self._running_tasks[execution_id]
                task.cancel()
                del self._running_tasks[execution_id]
            
            # Update execution status
            update_data = JobExecutionUpdate(
                status=ExecutionStatus.CANCELLED,
                completed_at=datetime.now()
            )
            update_job_execution(execution_id, update_data)
            
            # Update job status
            from backend.api.models.job_model import JobUpdate
            update_job(execution.job_id, 0, JobUpdate(status=JobStatus.CANCELLED))
            
            logger.info(f"Cancelled mock pipeline execution {execution_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error cancelling execution {execution_id}: {e}", exc_info=True)
            return False


# Singleton instance
_mock_runner_instance: Optional[MockPipelineRunner] = None


def get_mock_pipeline_runner() -> MockPipelineRunner:
    """Get or create singleton mock pipeline runner instance."""
    global _mock_runner_instance
    if _mock_runner_instance is None:
        _mock_runner_instance = MockPipelineRunner()
    return _mock_runner_instance
