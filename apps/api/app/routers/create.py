from fastapi import APIRouter, Depends, HTTPException

from app.schemas import CreateJob, CreateJobRequest
from app.services.auth_service import require_user
from app.services.create_service import create_generation_job, get_generation_job

router = APIRouter(prefix="/create", tags=["create"])


@router.post("/jobs", response_model=CreateJob)
def create_job(payload: CreateJobRequest, user=Depends(require_user)) -> CreateJob:
    return create_generation_job(user.id, payload.prompt, payload.files)


@router.get("/jobs/{job_id}", response_model=CreateJob)
def get_job(job_id: str) -> CreateJob:
    job = get_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/publish", response_model=CreateJob)
def publish_job(job_id: str) -> CreateJob:
    job = get_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
