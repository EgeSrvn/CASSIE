"""
User data models for CASSIE backend.

This module defines Pydantic models for user-related data structures,
matching the database schema defined in schemas.sql.
"""

from pydantic import BaseModel, EmailStr, Field
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """Base user model with common fields."""
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: Optional[EmailStr] = Field(None, max_length=100, description="User email address")
    bucket_name: str = Field(..., max_length=100, description="Per-user S3 bucket name")


class UserCreate(UserBase):
    """Model for creating a new user."""
    password: str = Field(..., min_length=8, description="Plain text password (will be hashed)")


class UserUpdate(BaseModel):
    """Model for updating user information."""
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8)


class UserInDB(UserBase):
    """User model as stored in database."""
    id: int
    password_hash: str = Field(..., alias="password_hash")
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
        populate_by_name = True


class UserResponse(UserBase):
    """User model for API responses (excludes sensitive data)."""
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True
