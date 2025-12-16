from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Integer, String, Text

from backend.api.database.db_init import Base


class CommunityWorkflow(Base):
  __tablename__ = "community_workflows"

  id = Column(Integer, primary_key=True, index=True)
  name = Column(String(255), nullable=False)
  description = Column(Text, nullable=True)

  tags = Column(JSON, nullable=True)  # list[str]
  author = Column(String(255), nullable=True)

  downloads = Column(Integer, nullable=False, default=0)
  upvotes = Column(Integer, nullable=False, default=0)
  downvotes = Column(Integer, nullable=False, default=0)
  votes = Column(Integer, nullable=False, default=0)

  comments = Column(JSON, nullable=True)  # list[{author, text}]
  nodes = Column(JSON, nullable=True)
  edges = Column(JSON, nullable=True)

  created_at = Column(DateTime, default=datetime.utcnow, nullable=False)


class CommunityWorkflowBase(BaseModel):
  name: str
  description: Optional[str] = None
  tags: Optional[List[str]] = None
  author: Optional[str] = None
  nodes: Optional[list] = None
  edges: Optional[list] = None


class CommunityWorkflowCreate(CommunityWorkflowBase):
  pass


class CommunityWorkflowRead(CommunityWorkflowBase):
  id: int
  downloads: int
  upvotes: int
  downvotes: int
  votes: int
  comments: Optional[list] = None

  class Config:
    from_attributes = True


