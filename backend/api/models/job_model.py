from datetime import datetime
from typing import List, Optional

from pydantic import BaseModel
from sqlalchemy import JSON, Column, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import relationship

from backend.api.database.db_init import Base


class Job(Base):
  __tablename__ = "jobs"

  id = Column(Integer, primary_key=True, index=True)
  user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)

  name = Column(String(255), nullable=False)
  pipeline = Column(String(255), nullable=True)
  notes = Column(Text, nullable=True)

  status = Column(String(50), nullable=False, default="pending")
  estimated_time = Column(Float, nullable=True)
  estimated_price = Column(Float, nullable=True)

  analyses = Column(JSON, nullable=True)  # list of strings
  files = Column(JSON, nullable=True)  # list of file names or descriptors
  results = Column(JSON, nullable=True)  # arbitrary structure (text, URLs, etc.)

  created_at = Column(DateTime, default=datetime.utcnow, nullable=False)
  completed_at = Column(DateTime, nullable=True)

  user = relationship("User", backref="jobs")


class JobBase(BaseModel):
  name: str
  pipeline: Optional[str] = None
  notes: Optional[str] = None
  estimated_time: Optional[float] = None
  estimated_price: Optional[float] = None
  analyses: Optional[List[str]] = None
  files: Optional[List[str]] = None


class JobCreate(JobBase):
  pass


class JobRead(JobBase):
  id: int
  status: str
  results: Optional[dict] = None
  created_at: datetime
  completed_at: Optional[datetime] = None

  class Config:
    from_attributes = True


