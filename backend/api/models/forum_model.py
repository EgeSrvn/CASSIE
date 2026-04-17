from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel, Field


class ForumAuthorResponse(BaseModel):
    id: int
    username: str
    display_name: Optional[str] = None
    affiliation: Optional[str] = None
    avatar_url: Optional[str] = None


class ForumThreadCreate(BaseModel):
    title: str = Field(..., min_length=5, max_length=200)
    body: str = Field(..., min_length=10, max_length=8000)


class ForumAnswerCreate(BaseModel):
    body: str = Field(..., min_length=2, max_length=8000)


class ForumCommentCreate(BaseModel):
    body: str = Field(..., min_length=1, max_length=4000)
    parent_comment_id: Optional[int] = None


class ForumCommentResponse(BaseModel):
    id: int
    thread_id: int
    answer_id: Optional[int] = None
    parent_comment_id: Optional[int] = None
    user_id: int
    body: str
    image_urls: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: datetime
    author: ForumAuthorResponse
    parent_comment_preview: Optional[dict] = None
    replies: List["ForumCommentResponse"] = Field(default_factory=list)


class ForumAnswerResponse(BaseModel):
    id: int
    thread_id: int
    user_id: int
    body: str
    created_at: datetime
    updated_at: datetime
    author: ForumAuthorResponse
    comments: List[ForumCommentResponse] = Field(default_factory=list)


class ForumThreadSummaryResponse(BaseModel):
    id: int
    user_id: int
    title: str
    body: str
    image_urls: List[str] = Field(default_factory=list)
    view_count: int
    answer_count: int
    comment_count: int
    created_at: datetime
    updated_at: datetime
    last_activity_at: datetime
    author: ForumAuthorResponse


class ForumThreadDetailResponse(ForumThreadSummaryResponse):
    thread_comments: List[ForumCommentResponse] = Field(default_factory=list)
    answers: List[ForumAnswerResponse] = Field(default_factory=list)


class ForumThreadListResponse(BaseModel):
    items: List[ForumThreadSummaryResponse] = Field(default_factory=list)
    total: int
    page: int
    per_page: int


ForumCommentResponse.model_rebuild()
