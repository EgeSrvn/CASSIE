from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.database.db_init import get_db
from backend.api.models.community_model import (
  CommunityWorkflow,
  CommunityWorkflowRead,
)
from backend.api.models.user_model import User
from backend.api.routes.auth import get_current_user


router = APIRouter(prefix="/api/community", tags=["community"])


@router.get("/workflows", response_model=List[CommunityWorkflowRead])
def list_workflows(db: Session = Depends(get_db)):
  workflows = db.query(CommunityWorkflow).order_by(CommunityWorkflow.votes.desc()).all()
  return [CommunityWorkflowRead.model_validate(w) for w in workflows]


@router.post("/workflows/{workflow_id}/vote")
def upvote_workflow(
  workflow_id: int,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
  workflow = db.query(CommunityWorkflow).filter(CommunityWorkflow.id == workflow_id).first()
  if not workflow:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Workflow not found")

  workflow.upvotes = (workflow.upvotes or 0) + 1
  workflow.votes = (workflow.votes or 0) + 1
  db.add(workflow)
  db.commit()

  return {"status": "ok", "id": workflow_id, "votes": workflow.votes}


