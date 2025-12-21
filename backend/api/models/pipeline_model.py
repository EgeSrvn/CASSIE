"""
Pipeline, workflow, and dataset data models for CASSIE backend.

This module defines Pydantic models for pipeline-related data structures,
matching the database schema defined in schemas.sql.
"""

from pydantic import BaseModel, Field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum


class WorkflowType(str, Enum):
    """Workflow type enumeration."""
    PREDEFINED = "predefined"
    CUSTOM = "custom"
    TEMPLATE = "template"


class ValidationStatus(str, Enum):
    """Workflow validation status enumeration."""
    PENDING = "pending"
    VALID = "valid"
    INVALID = "invalid"
    ERROR = "error"


class FileType(str, Enum):
    """File type enumeration."""
    INPUT = "input"
    OUTPUT = "output"
    INTERMEDIATE = "intermediate"
    LOG = "log"


class VoteType(str, Enum):
    """Vote type enumeration."""
    UPVOTE = "upvote"
    DOWNVOTE = "downvote"


# ============================================================================
# Workflow Models
# ============================================================================

class WorkflowBase(BaseModel):
    """Base workflow model with common fields."""
    name: str = Field(..., min_length=1, max_length=200, description="Workflow name")
    description: Optional[str] = Field(None, description="Workflow description")
    workflow_type: WorkflowType = Field(..., description="Type of workflow")
    workflow_content: str = Field(..., description="Complete Nextflow .nf file content")
    original_filename: Optional[str] = Field(None, max_length=255, description="Original filename if uploaded")
    tools_used: Optional[List[str]] = Field(None, description="List of tools used in workflow")
    workflow_steps: Optional[List[Dict[str, Any]]] = Field(None, description="Ordered workflow steps with metadata")
    parameters_schema: Optional[Dict[str, Any]] = Field(None, description="Parameter definitions and validation rules")
    is_public: bool = Field(False, description="Whether workflow can be shared")


class WorkflowCreate(WorkflowBase):
    """Model for creating a new workflow."""
    pass


class WorkflowUpdate(BaseModel):
    """Model for updating workflow information."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    workflow_content: Optional[str] = None
    tools_used: Optional[List[str]] = None
    workflow_steps: Optional[List[Dict[str, Any]]] = None
    parameters_schema: Optional[Dict[str, Any]] = None
    validation_status: Optional[ValidationStatus] = None
    validation_error: Optional[str] = None
    is_public: Optional[bool] = None
    is_active: Optional[bool] = None


class WorkflowInDB(WorkflowBase):
    """Workflow model as stored in database."""
    id: int
    user_id: Optional[int] = None
    validation_status: ValidationStatus = ValidationStatus.PENDING
    validation_error: Optional[str] = None
    version: int = 1
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
    created_by_user_id: Optional[int] = None

    class Config:
        from_attributes = True


class WorkflowResponse(WorkflowInDB):
    """Workflow model for API responses."""
    pass


# ============================================================================
# Pipeline Config Models
# ============================================================================

class PipelineConfigBase(BaseModel):
    """Base pipeline config model."""
    name: str = Field(..., min_length=1, max_length=200, description="Configuration name")
    description: Optional[str] = Field(None, description="Configuration description")
    workflow_id: int = Field(..., description="ID of the workflow this config belongs to")
    config_data: Dict[str, Any] = Field(..., description="Parameter values as JSON")


class PipelineConfigCreate(PipelineConfigBase):
    """Model for creating a new pipeline config."""
    pass


class PipelineConfigUpdate(BaseModel):
    """Model for updating pipeline config."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    config_data: Optional[Dict[str, Any]] = None


class PipelineConfigInDB(PipelineConfigBase):
    """Pipeline config model as stored in database."""
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PipelineConfigResponse(PipelineConfigInDB):
    """Pipeline config model for API responses."""
    pass


# ============================================================================
# Pipeline Models (Visual Pipeline Builder)
# ============================================================================

class PipelineBase(BaseModel):
    """Base pipeline model for visual pipeline builder."""
    name: str = Field(..., min_length=1, max_length=255, description="Pipeline name")
    description: Optional[str] = Field(None, description="Pipeline description")
    nodes: List[Dict[str, Any]] = Field(..., description="ReactFlow nodes as array")
    edges: List[Dict[str, Any]] = Field(..., description="ReactFlow edges as array")


class PipelineCreate(PipelineBase):
    """Model for creating a new pipeline."""
    pass


class PipelineUpdate(BaseModel):
    """Model for updating pipeline."""
    name: Optional[str] = Field(None, min_length=1, max_length=255)
    description: Optional[str] = None
    nodes: Optional[List[Dict[str, Any]]] = None
    edges: Optional[List[Dict[str, Any]]] = None
    is_shared: Optional[bool] = None


class PipelineInDB(PipelineBase):
    """Pipeline model as stored in database."""
    id: int
    user_id: int
    saved_at: datetime
    is_shared: bool = Field(False, description="Whether the pipeline is shared with the community")

    class Config:
        from_attributes = True


class PipelineResponse(PipelineInDB):
    """Pipeline model for API responses."""
    pass


# ============================================================================
# File Models
# ============================================================================

class FileBase(BaseModel):
    """Base file model."""
    filename: str = Field(..., max_length=255, description="File name")
    s3_key: str = Field(..., max_length=500, description="Full S3 path in user's bucket")
    file_type: FileType = Field(..., description="Type of file")
    file_format: Optional[str] = Field(None, max_length=50, description="File format (fastq, fasta, etc.)")
    size_bytes: Optional[int] = Field(None, ge=0, description="File size in bytes")
    checksum: Optional[str] = Field(None, max_length=64, description="MD5 or SHA256 checksum")
    uploaded_at: Optional[datetime] = None


class FileCreate(FileBase):
    """Model for creating a new file record."""
    job_id: Optional[int] = Field(None, description="ID of the job this file belongs to (optional for pre-upload)")


class FileUpdate(BaseModel):
    """Model for updating file information."""
    job_id: Optional[int] = None
    filename: Optional[str] = None
    file_format: Optional[str] = None
    size_bytes: Optional[int] = None
    checksum: Optional[str] = None


class FileInDB(FileBase):
    """File model as stored in database."""
    id: int
    job_id: Optional[int] = None  # Can be None for staging files or folder files
    folder_id: Optional[int] = None  # Can be None for job files
    created_at: datetime

    class Config:
        from_attributes = True


class FileResponse(FileInDB):
    """File model for API responses."""
    pass


# ============================================================================
# Dataset Models
# ============================================================================

class DatasetBase(BaseModel):
    """Base dataset model."""
    name: str = Field(..., min_length=1, max_length=200, description="Dataset name")
    description: Optional[str] = Field(None, description="Dataset description")
    file_id: int = Field(..., description="ID of the file this dataset references")
    data_type: Optional[str] = Field(None, max_length=50, description="Data type (fastq, fasta, pacbio, etc.)")
    is_imported: bool = Field(False, description="Whether dataset was imported")


class DatasetCreate(DatasetBase):
    """Model for creating a new dataset."""
    pass


class DatasetUpdate(BaseModel):
    """Model for updating dataset information."""
    name: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    data_type: Optional[str] = None


class DatasetInDB(DatasetBase):
    """Dataset model as stored in database."""
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class DatasetResponse(DatasetInDB):
    """Dataset model for API responses."""
    pass


# ============================================================================
# Community Workflow Models
# ============================================================================

class CommunityWorkflowBase(BaseModel):
    """Base community workflow model."""
    title: str = Field(..., min_length=1, max_length=200, description="Workflow title")
    description: Optional[str] = Field(None, description="Workflow description")
    workflow_id: int = Field(..., description="ID of the workflow")
    tags: Optional[List[str]] = Field(None, description="List of tags for categorization")
    is_featured: bool = Field(False, description="Whether workflow is featured")


class CommunityWorkflowCreate(CommunityWorkflowBase):
    """Model for creating a new community workflow."""
    pass


class CommunityWorkflowUpdate(BaseModel):
    """Model for updating community workflow."""
    title: Optional[str] = Field(None, min_length=1, max_length=200)
    description: Optional[str] = None
    tags: Optional[List[str]] = None
    is_featured: Optional[bool] = None


class CommunityWorkflowInDB(CommunityWorkflowBase):
    """Community workflow model as stored in database."""
    id: int
    published_by_user_id: Optional[int] = None
    popularity_score: int = 0
    usage_count: int = 0
    published_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class CommunityWorkflowResponse(CommunityWorkflowInDB):
    """Community workflow model for API responses."""
    pass


# ============================================================================
# Saved Workflow Models
# ============================================================================

class SavedWorkflowBase(BaseModel):
    """Base saved workflow model."""
    community_workflow_id: int = Field(..., description="ID of the community workflow")
    workflow_id: int = Field(..., description="ID of the user's copy of the workflow")


class SavedWorkflowCreate(SavedWorkflowBase):
    """Model for creating a new saved workflow."""
    pass


class SavedWorkflowInDB(SavedWorkflowBase):
    """Saved workflow model as stored in database."""
    id: int
    user_id: int
    saved_at: datetime
    last_used_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class SavedWorkflowResponse(SavedWorkflowInDB):
    """Saved workflow model for API responses."""
    pass


# ============================================================================
# Vote Models
# ============================================================================

class VoteBase(BaseModel):
    """Base vote model."""
    community_workflow_id: int = Field(..., description="ID of the community workflow")
    vote_type: VoteType = Field(..., description="Type of vote (upvote/downvote)")


class VoteCreate(VoteBase):
    """Model for creating a new vote."""
    pass


class VoteUpdate(BaseModel):
    """Model for updating a vote."""
    vote_type: VoteType


class VoteInDB(VoteBase):
    """Vote model as stored in database."""
    id: int
    user_id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class VoteResponse(VoteInDB):
    """Vote model for API responses."""
    pass


# ============================================================================
# Execution Dataset Models
# ============================================================================

class ExecutionDatasetBase(BaseModel):
    """Base execution dataset model."""
    execution_id: int = Field(..., description="ID of the job execution")
    dataset_id: int = Field(..., description="ID of the dataset")
    role: Optional[str] = Field(None, max_length=50, description="Dataset role (primary, secondary, reference, etc.)")


class ExecutionDatasetCreate(ExecutionDatasetBase):
    """Model for creating a new execution dataset link."""
    pass


class ExecutionDatasetInDB(ExecutionDatasetBase):
    """Execution dataset model as stored in database."""
    id: int
    created_at: datetime

    class Config:
        from_attributes = True


class ExecutionDatasetResponse(ExecutionDatasetInDB):
    """Execution dataset model for API responses."""
    pass

