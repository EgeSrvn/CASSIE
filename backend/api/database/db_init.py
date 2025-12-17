import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base, Session


DATABASE_URL = os.getenv(
    "DATABASE_URL",
    # Default is suitable for a local Postgres running in Docker with service name "postgres"
    "postgresql+psycopg2://postgres:postgres@postgres:5432/cassie",
)

engine = create_engine(DATABASE_URL, future=True)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine, future=True)

Base = declarative_base()


def get_db() -> Session:
  """
  FastAPI dependency that provides a SQLAlchemy session and ensures it is closed.
  """
  db = SessionLocal()
  try:
    yield db
  finally:
    db.close()


def init_db():
  """
  Import models and create tables if they do not exist.
  Call this once at application startup.
  """
  # Local imports to avoid circular dependencies
  from backend.api.models import user_model, job_model, pipeline_model, community_model  # noqa: F401

  Base.metadata.create_all(bind=engine)


