"""
User data models for CASSIE backend.

This module defines Pydantic models for user-related data structures,
matching the database schema defined in schemas.sql.
"""

from pydantic import BaseModel, EmailStr, Field, field_validator
from typing import Optional
from datetime import datetime


class UserBase(BaseModel):
    """Base user model with common fields."""
    username: str = Field(..., min_length=3, max_length=50, description="Unique username")
    email: Optional[EmailStr] = Field(None, max_length=100, description="User email address")
    bucket_name: str = Field(..., max_length=100, description="Legacy per-user storage namespace")
    display_name: Optional[str] = Field(None, max_length=120, description="Public display name")
    bio: Optional[str] = Field(None, description="Short user biography")
    affiliation: Optional[str] = Field(None, max_length=255, description="Institution or team")
    job_title: Optional[str] = Field(None, max_length=120, description="Role or title")
    location: Optional[str] = Field(None, max_length=120, description="Location")
    website_url: Optional[str] = Field(None, max_length=500, description="Website URL")
    avatar_url: Optional[str] = Field(None, max_length=500, description="Avatar image URL")
    cash_balance_usd: float = Field(0.0, ge=0, description="Spendable cash balance available for new CASSIE jobs")
    cash_reserved_usd: float = Field(0.0, ge=0, description="Balance currently reserved as active job holds")
    cash_available_usd: float = Field(0.0, ge=0, description="Spendable balance that can be reserved for new jobs")
    email_verified: bool = Field(False, description="Whether the email address has been verified")
    login_two_factor_enabled: bool = Field(False, description="Whether email-based login 2FA is enabled")
    job_notifications_enabled: bool = Field(False, description="Whether email job notifications are enabled")
    is_admin: bool = Field(False, description="Whether user has admin privileges")
    is_active: bool = Field(True, description="Whether user account is active")


class UserCreate(UserBase):
    """Model for creating a new user."""
    password: str = Field(..., min_length=8, description="Plain text password (will be hashed)")


class UserUpdate(BaseModel):
    """Model for updating user information."""
    email: Optional[EmailStr] = None
    password: Optional[str] = Field(None, min_length=8)
    display_name: Optional[str] = Field(None, max_length=120)
    bio: Optional[str] = None
    affiliation: Optional[str] = Field(None, max_length=255)
    job_title: Optional[str] = Field(None, max_length=120)
    location: Optional[str] = Field(None, max_length=120)
    website_url: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = Field(None, max_length=500)

    @field_validator("email", "display_name", "bio", "affiliation", "job_title", "location", "website_url", "avatar_url", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class UserProfileUpdate(BaseModel):
    """Editable profile fields for the current user."""
    email: Optional[EmailStr] = None
    display_name: Optional[str] = Field(None, max_length=120)
    bio: Optional[str] = None
    affiliation: Optional[str] = Field(None, max_length=255)
    job_title: Optional[str] = Field(None, max_length=120)
    location: Optional[str] = Field(None, max_length=120)
    website_url: Optional[str] = Field(None, max_length=500)
    avatar_url: Optional[str] = Field(None, max_length=500)
    current_password: Optional[str] = Field(None, min_length=1)
    new_password: Optional[str] = Field(None, min_length=8)
    login_two_factor_enabled: Optional[bool] = None
    job_notifications_enabled: Optional[bool] = None

    @field_validator("email", "display_name", "bio", "affiliation", "job_title", "location", "website_url", "avatar_url", "current_password", "new_password", mode="before")
    @classmethod
    def empty_string_to_none(cls, value):
        if isinstance(value, str) and not value.strip():
            return None
        return value


class UserInDB(UserBase):
    """User model as stored in database."""
    id: int
    password_hash: str = Field(..., alias="password_hash")
    email_verification_code: Optional[str] = None
    email_verification_expires_at: Optional[datetime] = None
    password_reset_code: Optional[str] = None
    password_reset_expires_at: Optional[datetime] = None
    login_two_factor_code: Optional[str] = None
    login_two_factor_expires_at: Optional[datetime] = None
    suspended_until: Optional[datetime] = None
    suspension_reason: Optional[str] = None
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
