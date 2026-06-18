from datetime import datetime, timezone
from uuid import uuid4

from fastapi import APIRouter, HTTPException

from app.schemas import AgentLog, CreateJob, CreateJobRequest

router = APIRouter(prefix="/create", tags=["create"])
JOBS: dict[str, CreateJob] = {}


@router.post("/jobs", response_model=CreateJob)
def create_job(payload: CreateJobRequest) -> CreateJob:
    job = CreateJob(
        id=f"job_{uuid4().hex[:10]}",
        status="stubbed",
        prompt=payload.prompt,
        createdAt=datetime.now(timezone.utc),
        logs=[
            AgentLog(
                stage="create",
                status="skipped",
                message="Create generation is intentionally stubbed; API contract is preserved.",
            )
        ],
    )
    JOBS[job.id] = job
    return job


@router.get("/jobs/{job_id}", response_model=CreateJob)
def get_job(job_id: str) -> CreateJob:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/publish", response_model=CreateJob)
def publish_job(job_id: str) -> CreateJob:
    job = JOBS.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job
