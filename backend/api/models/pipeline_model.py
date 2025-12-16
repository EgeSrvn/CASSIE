from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.api.database.db_init import Base


class Pipeline(Base):
  __tablename__ = "pipelines"

  id = Column(Integer, primary_key=True, index=True)
  user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

  name = Column(String(255), nullable=False)
  description = Column(Text, nullable=True)
  nodes = Column(JSON, nullable=True)
  edges = Column(JSON, nullable=True)
  saved_at = Column(DateTime, default=datetime.utcnow, nullable=False)

  user = relationship("User", backref="pipelines")


class PipelineBase(BaseModel):
  name: str
  description: Optional[str] = None
  nodes: Optional[list] = None
  edges: Optional[list] = None


class PipelineCreate(PipelineBase):
  pass


class PipelineRead(PipelineBase):
  id: int
  saved_at: datetime

  class Config:
    from_attributes = True


