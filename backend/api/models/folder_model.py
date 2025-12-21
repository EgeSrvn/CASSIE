"""
Folder models for data management.

This module defines Pydantic models for folder operations.
"""

from pydantic import BaseModel, Field
from typing import Optional, List
from datetime import datetime


class FolderBase(BaseModel):
    """Base folder model."""
    name: str = Field(..., min_length=1, max_length=255, description="Folder name")
    parent_folder_id: Optional[int] = Field(None, description="Parent folder ID for nested folders")


class FolderCreate(FolderBase):
    """Model for creating a new folder."""
    pass


class FolderUpdate(BaseModel):
    """Model for updating folder information."""
    name: Optional[str] = Field(None, min_length=1, max_length=255, description="New folder name")
    parent_folder_id: Optional[int] = Field(None, description="New parent folder ID")


class FolderInDB(FolderBase):
    """Folder model as stored in database."""
    id: int
    user_id: int
    path: str
    created_at: datetime
    updated_at: datetime
    
    class Config:
        from_attributes = True


class FolderResponse(FolderInDB):
    """Folder model for API responses."""
    pass


class FolderTreeItem(FolderInDB):
    """Folder with nested children and files."""
    children: List['FolderTreeItem'] = []
    files: List[dict] = []  # File metadata


# Update forward references
FolderTreeItem.model_rebuild()

