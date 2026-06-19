from fastapi import APIRouter, Depends, HTTPException, Request

from app.schemas import (
    AIConfigRequest,
    AIConfigState,
    CreateJob,
    CreateJobRequest,
    CreateProject,
    CreateRun,
    CreateRunStep,
    LLMTestResult,
    RecentGame,
)
from app.agents.framework import (
    get_agent_state_for_job,
    get_project,
    get_projects,
    get_run,
    get_run_steps,
)
from app.services.auth_service import get_optional_user, require_user
from app.services.create_service import (
    create_generation_job,
    get_ai_config_state,
    get_generation_job,
    get_recent_game,
    test_ai_config_payload,
    upsert_ai_config,
)

router = APIRouter(prefix="/create", tags=["create"])


@router.get("/ai-config", response_model=AIConfigState)
def ai_config_state(request: Request, user=Depends(get_optional_user)) -> AIConfigState:
    return get_ai_config_state(user, getattr(request.state, "jwt_jti", None))


@router.put("/ai-config", response_model=AIConfigState)
def save_ai_config(
    payload: AIConfigRequest,
    request: Request,
    user=Depends(require_user),
) -> AIConfigState:
    return upsert_ai_config(user.id, payload, getattr(request.state, "jwt_jti", None))


@router.post("/ai-config/test", response_model=LLMTestResult)
def test_ai_config(payload: AIConfigRequest, user=Depends(require_user)) -> LLMTestResult:
    return test_ai_config_payload(payload)


@router.get("/recent-game", response_model=RecentGame | None)
def recent_game(user=Depends(require_user)) -> RecentGame | None:
    return get_recent_game(user.id)


@router.get("/projects", response_model=list[CreateProject])
def list_projects(user=Depends(require_user)) -> list[CreateProject]:
    return [CreateProject(**project) for project in get_projects(user.id)]


@router.get("/projects/{project_id}", response_model=CreateProject)
def project_detail(project_id: str, user=Depends(require_user)) -> CreateProject:
    project = get_project(user.id, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return CreateProject(**project)


@router.get("/runs/{run_id}", response_model=CreateRun)
def run_detail(run_id: str, user=Depends(require_user)) -> CreateRun:
    run = get_run(user.id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")
    return CreateRun(**run)


@router.get("/runs/{run_id}/steps", response_model=list[CreateRunStep])
def run_steps(run_id: str, user=Depends(require_user)) -> list[CreateRunStep]:
    steps = get_run_steps(user.id, run_id)
    if steps is None:
        raise HTTPException(status_code=404, detail="Run not found")
    return [CreateRunStep(**step) for step in steps]


@router.post("/jobs", response_model=CreateJob)
def create_job(payload: CreateJobRequest, request: Request, user=Depends(require_user)) -> CreateJob:
    return create_generation_job(
        user.id,
        payload.prompt,
        payload.files,
        payload.agentMode,
        payload.createType,
        payload.projectId,
        getattr(request.state, "jwt_jti", None),
    )


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


@router.get("/jobs/{job_id}/agent-state")
def job_agent_state(job_id: str, user=Depends(require_user)) -> dict:
    state = get_agent_state_for_job(user.id, job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Agent state not found")
    return state
