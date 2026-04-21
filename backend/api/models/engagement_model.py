from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class VoteType(str, Enum):
    UPVOTE = "upvote"
    DOWNVOTE = "downvote"


class ReportTargetType(str, Enum):
    PIPELINE = "pipeline"
    FORUM_THREAD = "forum_thread"
    FORUM_COMMENT = "forum_comment"


class VoteRequest(BaseModel):
    vote_type: VoteType = Field(..., description="Type of vote to apply")


class EngagementSummary(BaseModel):
    upvote_count: int = 0
    downvote_count: int = 0
    score: int = 0
    user_vote: Optional[VoteType] = None


class ReportCreate(BaseModel):
    reason: str = Field(..., min_length=3, max_length=160)
    details: Optional[str] = Field(None, max_length=2000)


class ModerationReportResponse(BaseModel):
    id: int
    reporter_user_id: int
    target_type: ReportTargetType
    target_id: int
    reason: str
    details: Optional[str] = None
    status: str
    created_at: datetime
    updated_at: datetime
