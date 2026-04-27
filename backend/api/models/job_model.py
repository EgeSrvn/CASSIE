"""
Job and execution data models for CASSIE backend.

This module defines Pydantic models for job-related data structures,
matching the database schema defined in schemas.sql.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class JobStatus(str, Enum):
    """Job status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class ExecutionStatus(str, Enum):
    """Execution status enumeration."""
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


class CloudProvider(str, Enum):
    """Cloud provider enumeration."""
    AWS = "aws"
    GCP = "gcp"
    AZURE = "azure"
    LOCAL = "local"


class JobBase(BaseModel):
    """Base job model with common fields."""
    name: str = Field(..., min_length=1, max_length=100, description="Job name")
    workflow_id: Optional[int] = Field(None, description="ID of the workflow to execute (optional if tool_indices provided)")
    tool_indices: Optional[List[int]] = Field(None, description="Tool indices to use (e.g., [0] for FastQC). Workflow will be created dynamically.")
    pipeline_config_id: Optional[int] = Field(None, description="Optional pipeline configuration ID")
    pipeline_id: Optional[int] = Field(None, description="Optional saved pipeline ID (visual pipeline builder)")
    assembler: Optional[str] = Field(None, max_length=50, description="Assembler tool name")
    data_types: Optional[List[str]] = Field(None, description="List of data types (e.g., ['pacbio', 'hic'])")
    cloud_provider: Optional[CloudProvider] = Field(None, description="Cloud provider for execution")
    execution_preferences: Optional[Dict[str, Any]] = Field(None, description="Per-job execution ordering preferences")
    vm_name: Optional[str] = Field(None, max_length=50, description="Virtual machine name for execution (e.g., 'vm1', 'vm2')")
    input_file_ids: Optional[List[int]] = Field(None, description="List of data library file IDs to associate with this job")
    staged_input_file_ids: Optional[List[int]] = Field(None, description="List of staged storage file IDs to associate with this job")


class JobCreate(JobBase):
    """Model for creating a new job."""
    pending_upload_count: Optional[int] = Field(None, ge=0, description="Number of browser-side files queued for background upload")
    expected_total_input_files: Optional[int] = Field(None, ge=0, description="Expected total number of input files after queued uploads finish")
    estimated_price_usd: Optional[float] = Field(None, ge=0, description="Estimated job price used for balance reservation")


class JobUpdate(BaseModel):
    """Model for updating job information."""
    name: Optional[str] = Field(None, min_length=1, max_length=100)
    status: Optional[JobStatus] = None
    assembler: Optional[str] = None
    data_types: Optional[List[str]] = None
    cloud_provider: Optional[CloudProvider] = None
    execution_preferences: Optional[Dict[str, Any]] = None
    vm_name: Optional[str] = Field(None, max_length=50)


class JobInDB(JobBase):
    """Job model as stored in database."""
    id: int
    user_id: int
    status: JobStatus = JobStatus.PENDING
    estimated_price_usd: float = 0.0
    max_charge_usd: float = 0.0
    actual_price_charged_usd: Optional[float] = None
    balance_reserved_at: Optional[datetime] = None
    balance_charged_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class JobResponse(JobInDB):
    """Job model for API responses."""
    interactive_outputs_enabled: Optional[bool] = None


class JobCreateResponse(JobResponse):
    """Job response returned immediately after job creation."""
    upload_session_token: Optional[str] = None
    pending_upload_count: Optional[int] = None
    expected_total_input_files: Optional[int] = None


class JobExecutionBase(BaseModel):
    """Base job execution model."""
    execution_number: int = Field(..., ge=1, description="Execution attempt number (1, 2, 3...)")
    nextflow_run_id: Optional[str] = Field(None, max_length=100, description="Nextflow execution ID")
    work_dir: Optional[str] = Field(None, max_length=500, description="Nextflow work directory")
    output_dir: Optional[str] = Field(None, max_length=500, description="Nextflow output directory")
    process_id: Optional[int] = Field(None, description="System process ID")
    tool_versions: Optional[Dict[str, str]] = Field(None, description="Tool versions used")
    parameters_used: Optional[Dict[str, Any]] = Field(None, description="Parameters used in execution")
    error_message: Optional[str] = Field(None, description="Error message if failed")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobExecutionCreate(JobExecutionBase):
    """Model for creating a new job execution."""
    job_id: int = Field(..., description="ID of the parent job")
    status: ExecutionStatus = ExecutionStatus.RUNNING


class JobExecutionUpdate(BaseModel):
    """Model for updating job execution."""
    status: Optional[ExecutionStatus] = None
    nextflow_run_id: Optional[str] = None
    work_dir: Optional[str] = None
    output_dir: Optional[str] = None
    process_id: Optional[int] = None
    tool_versions: Optional[Dict[str, str]] = None
    parameters_used: Optional[Dict[str, Any]] = None
    error_message: Optional[str] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class JobExecutionInDB(JobExecutionBase):
    """Job execution model as stored in database."""
    id: int
    job_id: int
    status: ExecutionStatus = ExecutionStatus.RUNNING
    created_at: datetime

    class Config:
        from_attributes = True


class JobExecutionResponse(JobExecutionInDB):
    """Job execution model for API responses."""
    pass
