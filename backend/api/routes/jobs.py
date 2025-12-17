from typing import List

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from backend.api.database.db_init import get_db
from backend.api.models.job_model import Job, JobCreate, JobRead
from backend.api.routes.auth import get_current_user
from backend.api.models.user_model import User


router = APIRouter(prefix="/api/jobs", tags=["jobs"])


@router.get("", response_model=List[JobRead])
def list_jobs(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
  jobs = (
    db.query(Job)
    .filter(Job.user_id == current_user.id)
    .order_by(Job.created_at.desc())
    .all()
  )
  return [JobRead.model_validate(j) for j in jobs]


@router.post("", response_model=JobRead, status_code=status.HTTP_201_CREATED)
def create_job(
  payload: JobCreate,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
  job = Job(
    user_id=current_user.id,
    name=payload.name,
    pipeline=payload.pipeline,
    notes=payload.notes,
    estimated_time=payload.estimated_time,
    estimated_price=payload.estimated_price,
    analyses=payload.analyses,
    files=payload.files,
    status="pending",
  )
  db.add(job)
  db.commit()
  db.refresh(job)
  return JobRead.model_validate(job)


@router.get("/{job_id}", response_model=JobRead)
def get_job(
  job_id: int,
  current_user: User = Depends(get_current_user),
  db: Session = Depends(get_db),
):
  job = db.query(Job).filter(Job.id == job_id, Job.user_id == current_user.id).first()
  if not job:
    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
  return JobRead.model_validate(job)


