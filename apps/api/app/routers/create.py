import asyncio
import json

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse

from app.schemas import (
    AIConfigRequest,
    AIConfigState,
    AIConfigTestRequest,
    CreateJob,
    CreateJobRequest,
    CreateProject,
    CreateProjectDeleteResult,
    CreateProjectPreview,
    CreateRun,
    CreateRunStep,
    DecentralizedDecisionRequest,
    DecentralizedPreviewResponse,
    DecentralizedSelectionRequest,
    LLMTestResult,
    PlanDecisionRequest,
    PlanPreviewResponse,
    RecentGame,
    UserProfile,
)
from app.agents.framework import (
    get_agent_state_for_job,
    get_project,
    get_projects,
    get_run,
    get_run_steps,
)
from app.agents.framework.events import run_event_channel, sanitize_step_event
from app.services.auth_service import redis_client
from app.services.auth_service import get_optional_user, require_user
from app.services.create_service import (
    create_generation_job_start,
    choose_decentralized_candidate,
    delete_create_project,
    decide_plan_run,
    decide_decentralized_run,
    execute_decentralized_final_run,
    execute_generation_job,
    get_decentralized_preview_state,
    get_ai_config_state,
    get_generation_job,
    get_plan_preview,
    get_project_preview,
    get_recent_game,
    publish_generation_job,
    test_saved_or_payload_ai_config,
    upsert_ai_config,
)

router = APIRouter(prefix="/create", tags=["create"])


@router.get("/ai-config", response_model=AIConfigState, response_model_exclude_none=True)
def ai_config_state(request: Request, user=Depends(get_optional_user)) -> AIConfigState:
    return get_ai_config_state(user, getattr(request.state, "jwt_jti", None))


@router.put("/ai-config", response_model=AIConfigState, response_model_exclude_none=True)
def save_ai_config(
    payload: AIConfigRequest,
    request: Request,
    user=Depends(require_user),
) -> AIConfigState:
    return upsert_ai_config(user.id, payload, getattr(request.state, "jwt_jti", None))


@router.post("/ai-config/test", response_model=LLMTestResult)
def test_ai_config(
    request: Request,
    payload: AIConfigTestRequest | None = None,
    user=Depends(require_user),
) -> LLMTestResult:
    return test_saved_or_payload_ai_config(user.id, payload, getattr(request.state, "jwt_jti", None))


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


@router.delete("/projects/{project_id}", response_model=CreateProjectDeleteResult)
def delete_project(project_id: str, user=Depends(require_user)) -> CreateProjectDeleteResult:
    result = delete_create_project(user.id, project_id)
    if not result:
        raise HTTPException(status_code=404, detail="Project not found")
    return result


@router.get("/projects/{project_id}/preview", response_model=CreateProjectPreview)
def project_preview(project_id: str, user=Depends(require_user)) -> CreateProjectPreview:
    return CreateProjectPreview(**get_project_preview(user.id, project_id))


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


@router.get("/runs/{run_id}/plan-preview", response_model=PlanPreviewResponse)
def run_plan_preview(run_id: str, user=Depends(require_user)) -> PlanPreviewResponse:
    return PlanPreviewResponse(**get_plan_preview(user.id, run_id))


@router.post("/runs/{run_id}/plan-decision", response_model=CreateJob)
def run_plan_decision(
    run_id: str,
    payload: PlanDecisionRequest,
    request: Request,
    user=Depends(require_user),
) -> CreateJob:
    return decide_plan_run(user.id, run_id, payload.decision, getattr(request.state, "jwt_jti", None))


@router.get("/runs/{run_id}/decentralized-previews", response_model=DecentralizedPreviewResponse)
def run_decentralized_previews(run_id: str, user=Depends(require_user)) -> DecentralizedPreviewResponse:
    return DecentralizedPreviewResponse(**get_decentralized_preview_state(user.id, run_id))


@router.post("/runs/{run_id}/decentralized-selection", response_model=DecentralizedPreviewResponse)
def run_decentralized_selection(
    run_id: str,
    payload: DecentralizedSelectionRequest,
    user=Depends(require_user),
) -> DecentralizedPreviewResponse:
    return DecentralizedPreviewResponse(**choose_decentralized_candidate(user.id, run_id, payload.candidateId))


@router.post("/runs/{run_id}/decentralized-confirm", response_model=CreateJob)
def run_decentralized_confirm(
    run_id: str,
    payload: DecentralizedDecisionRequest,
    background_tasks: BackgroundTasks,
    request: Request,
    user=Depends(require_user),
) -> CreateJob:
    job = decide_decentralized_run(user.id, run_id, payload.decision, getattr(request.state, "jwt_jti", None))
    if payload.decision == "accepted":
        background_tasks.add_task(execute_decentralized_final_run, user.id, run_id, getattr(request.state, "jwt_jti", None))
    return job


@router.get("/runs/{run_id}/events")
def run_events(
    run_id: str,
    user=Depends(require_user),
    after_step_no: int = Query(0, alias="afterStepNo"),
) -> StreamingResponse:
    run = get_run(user.id, run_id)
    if not run:
        raise HTTPException(status_code=404, detail="Run not found")

    async def event_stream():
        last_step_no = after_step_no
        replay_steps = get_run_steps(user.id, run_id) or []
        for step in replay_steps:
            if step["stepNo"] <= last_step_no:
                continue
            event = sanitize_step_event(
                {
                    "runId": run_id,
                    "stepNo": step["stepNo"],
                    "stage": step["stage"],
                    "status": step["status"],
                    "inputSummary": step["inputSummary"],
                    "outputSummary": step["outputSummary"],
                    "metrics": step["metrics"],
                    "createdAt": step["createdAt"],
                }
            )
            last_step_no = step["stepNo"]
            yield f"event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
            if event["type"] in {"done", "error"}:
                return

        client = redis_client()
        pubsub = client.pubsub()
        pubsub.subscribe(run_event_channel(run_id))
        try:
            idle_ticks = 0
            while True:
                message = pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
                if message and message.get("data"):
                    event = json.loads(message["data"])
                    step_no = int(event.get("stepNo") or 0)
                    if step_no <= last_step_no:
                        continue
                    last_step_no = step_no
                    yield f"event: {event.get('type', 'step')}\ndata: {json.dumps(event, ensure_ascii=False, default=str)}\n\n"
                    if event.get("type") in {"done", "error"}:
                        return
                    idle_ticks = 0
                else:
                    idle_ticks += 1
                    if idle_ticks >= 15:
                        heartbeat = {"type": "heartbeat", "runId": run_id}
                        yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"
                        idle_ticks = 0
                    current_run = get_run(user.id, run_id)
                    if current_run and current_run["status"] in {"completed", "failed", "canceled"}:
                        event_type = "done" if current_run["status"] == "completed" else "error"
                        final_event = {
                            "type": event_type,
                            "runId": run_id,
                            "status": current_run["status"],
                            "summary": current_run.get("summary", {}),
                        }
                        yield f"event: {event_type}\ndata: {json.dumps(final_event, ensure_ascii=False, default=str)}\n\n"
                        return
                    await asyncio.sleep(0.1)
        finally:
            pubsub.close()

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post("/jobs", response_model=CreateJob, status_code=status.HTTP_202_ACCEPTED)
def create_job(payload: CreateJobRequest, background_tasks: BackgroundTasks, request: Request, user=Depends(require_user)) -> CreateJob:
    job = create_generation_job_start(
        creator_id=user.id,
        prompt=payload.prompt,
        files=payload.files,
        input_assets=payload.inputAssets,
        agent_mode=payload.agentMode,
        create_type=payload.createType,
        project_id=payload.projectId,
        jwt_jti=getattr(request.state, "jwt_jti", None),
    )
    background_tasks.add_task(execute_generation_job, job.id, user.id, getattr(request.state, "jwt_jti", None))
    return job


@router.get("/jobs/{job_id}", response_model=CreateJob)
def get_job(job_id: str, user: UserProfile = Depends(require_user)) -> CreateJob:
    job = get_generation_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")
    return job


@router.post("/jobs/{job_id}/publish", response_model=CreateJob)
def publish_job(job_id: str, user=Depends(require_user)) -> CreateJob:
    return publish_generation_job(user.id, job_id)


@router.get("/jobs/{job_id}/agent-state")
def job_agent_state(job_id: str, user=Depends(require_user)) -> dict:
    state = get_agent_state_for_job(user.id, job_id)
    if not state:
        raise HTTPException(status_code=404, detail="Agent state not found")
    return state
