from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.database.db_init import get_db
from backend.api.models.pipeline_model import Pipeline, PipelineCreate, PipelineRead
from backend.api.models.user_model import User
from backend.api.routes.auth import get_current_user


router = APIRouter(prefix="/api/pipelines", tags=["pipelines"])


@router.get("", response_model=List[PipelineRead])
def list_pipelines(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
  pipelines = (
    db.query(Pipeline)
    .filter(Pipeline.user_id == current_user.id)
    .order_by(Pipeline.saved_at.desc())
    .all()
  )
  return [PipelineRead.model_validate(p) for p in pipelines]


@router.post("", response_model=PipelineRead, status_code=status.HTTP_201_CREATED)
def create_pipeline(
  payload: PipelineCreate,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
  pipeline = Pipeline(
    user_id=current_user.id,
    name=payload.name,
    description=payload.description,
    nodes=payload.nodes,
    edges=payload.edges,
  )
  db.add(pipeline)
  db.commit()
  db.refresh(pipeline)
  return PipelineRead.model_validate(pipeline)


@router.delete("/{pipeline_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_pipeline(
  pipeline_id: int,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
  pipeline = (
    db.query(Pipeline)
    .filter(Pipeline.id == pipeline_id, Pipeline.user_id == current_user.id)
    .first()
  )
  if not pipeline:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pipeline not found")
  db.delete(pipeline)
  db.commit()
  return None


