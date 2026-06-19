from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from psycopg.types.json import Jsonb

from app.database import db_connection
from app.agents.framework.memory import LongTermMemory, PersistentMemory, ShortTermMemory
from app.agents.framework.run_log import RunLog
from app.agents.framework.schema import ensure_agent_framework_schema
from app.agents.framework.task_state import TaskState, TaskStateStore
from app.agents.framework.workspace import WorktreeManager, WorkspaceContext


@dataclass
class CreateAgentRunContext:
    project_id: str
    run_id: str
    task_id: str
    create_type: str
    agent_mode: str
    task_state: TaskState
    task_store: TaskStateStore
    run_log: RunLog
    persistent_memory: PersistentMemory
    long_term_memory: LongTermMemory
    short_term_memory: ShortTermMemory
    workspace: WorkspaceContext


def _normalize_create_type(create_type: str | None) -> str:
    value = (create_type or "init").strip().lower()
    if value not in {"init", "opt"}:
        raise HTTPException(status_code=422, detail="createType must be init or opt")
    return value


def _create_project(user_id: str, title: str) -> str:
    with db_connection() as connection:
        row = connection.execute(
            """
INSERT INTO agent_projects (user_id, title, status)
VALUES (%s, %s, 'active')
RETURNING id
""",
            (user_id, title[:160] or "Untitled project"),
        ).fetchone()
    return str(row["id"])


def _require_project(user_id: str, project_id: str | None) -> str:
    if not project_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "PROJECT_ID_REQUIRED", "message": "projectId is required when createType is opt."},
        )
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT id
FROM agent_projects
WHERE id = %s AND user_id = %s AND status = 'active'
LIMIT 1
""",
            (project_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Project not found")
    return str(row["id"])


def create_agent_run_context(
    *,
    user_id: str,
    prompt: str,
    files: list[str],
    agent_mode: str,
    create_type: str,
    project_id: str | None,
    session_id: str,
) -> CreateAgentRunContext:
    ensure_agent_framework_schema()
    normalized_create_type = _normalize_create_type(create_type)
    cleaned_prompt = prompt.strip() or "Create a fast arcade collection game with pointer controls."
    if normalized_create_type == "init":
        resolved_project_id = _create_project(user_id, cleaned_prompt[:80] or "Untitled project")
    else:
        resolved_project_id = _require_project(user_id, project_id)

    run_id = str(uuid4())
    task_id = str(uuid4())
    log_object_key = f"agent-runs/{run_id}/run-log.jsonl"
    with db_connection() as connection:
        connection.execute(
            """
INSERT INTO create_runs (
  id, task_id, project_id, user_id, create_type, agent_mode, status, summary, log_object_key
)
VALUES (%s, %s, %s, %s, %s, %s, 'running', %s, %s)
""",
            (
                run_id,
                task_id,
                resolved_project_id,
                user_id,
                normalized_create_type,
                agent_mode,
                Jsonb({"prompt": cleaned_prompt, "files": files}),
                log_object_key,
            ),
        )

    run_log = RunLog(run_id)
    task_store = TaskStateStore()
    task_state = TaskState(
        run_id=run_id,
        task_id=task_id,
        project_id=resolved_project_id,
        user_id=user_id,
        user_request=cleaned_prompt,
    )
    workspace = WorktreeManager().prepare(run_id=run_id, project_id=resolved_project_id)
    persistent_memory = PersistentMemory()
    long_term_memory = LongTermMemory(session_id, resolved_project_id)
    short_term_memory = ShortTermMemory(run_id)

    run_log.append(
        stage="run_created",
        status="succeeded",
        input_summary=f"{normalized_create_type} create request accepted.",
        output_summary="Create run, task state, and workspace stub initialized.",
        metrics={
            "projectId": resolved_project_id,
            "taskId": task_id,
            "workspaceCapability": workspace.capability,
            "isolationMode": workspace.isolation_mode,
            "worktreeStubPath": workspace.worktree_stub_path,
            "branchName": workspace.branch_name,
            "baseCommit": workspace.base_commit,
        },
    )
    task_store.checkpoint(
        task_state,
        "run_created",
        {"projectId": resolved_project_id, "files": files, "agentMode": agent_mode},
        run_log.object_key,
    )
    persistent_memory.put(
        user_id=user_id,
        project_id=resolved_project_id,
        memory_type="project_tag",
        tags=[normalized_create_type, agent_mode],
        summary="Create request metadata captured.",
        payload={"prompt": cleaned_prompt, "files": files, "agentMode": agent_mode},
    )
    long_term_memory.append_history("user", cleaned_prompt)
    short_term_memory.record_tool_call({"tool": "create_agent_run_context", "status": "succeeded"})

    return CreateAgentRunContext(
        project_id=resolved_project_id,
        run_id=run_id,
        task_id=task_id,
        create_type=normalized_create_type,
        agent_mode=agent_mode,
        task_state=task_state,
        task_store=task_store,
        run_log=run_log,
        persistent_memory=persistent_memory,
        long_term_memory=long_term_memory,
        short_term_memory=short_term_memory,
        workspace=workspace,
    )


def finalize_agent_run(
    *,
    context: CreateAgentRunContext,
    status_value: str,
    job_id: str | None = None,
    game_id: str | None = None,
    version_id: str | None = None,
    summary: dict[str, Any] | None = None,
    final_answer: str | None = None,
) -> None:
    context.task_state.status = status_value
    context.task_state.final_answer = final_answer
    context.task_store.checkpoint(context.task_state, f"run_{status_value}", summary or {}, context.run_log.object_key)
    with db_connection() as connection:
        connection.execute(
            """
UPDATE create_runs
SET
  job_id = %s,
  game_id = %s,
  version_id = %s,
  status = %s,
  summary = %s,
  completed_at = CASE WHEN %s IN ('completed', 'failed', 'canceled') THEN now() ELSE completed_at END
WHERE id = %s
""",
            (
                job_id,
                game_id,
                version_id,
                status_value,
                Jsonb(summary or {}),
                status_value,
                context.run_id,
            ),
        )
        if game_id:
            connection.execute(
                """
UPDATE agent_projects
SET game_id = %s, updated_at = now(), metadata = metadata || %s
WHERE id = %s
""",
                (game_id, Jsonb({"latestRunId": context.run_id, "latestJobId": job_id}), context.project_id),
            )


def get_projects(user_id: str) -> list[dict[str, Any]]:
    ensure_agent_framework_schema()
    with db_connection() as connection:
        rows = connection.execute(
            """
SELECT
  p.id,
  p.game_id,
  p.title,
  p.status,
  p.created_at,
  p.updated_at,
  r.id AS latest_run_id,
  r.status AS latest_run_status
FROM agent_projects p
LEFT JOIN LATERAL (
  SELECT id, status
  FROM create_runs
  WHERE project_id = p.id
  ORDER BY created_at DESC
  LIMIT 1
) r ON TRUE
WHERE p.user_id = %s AND p.status = 'active'
ORDER BY p.updated_at DESC
LIMIT 100
""",
            (user_id,),
        ).fetchall()
    return [
        {
            "projectId": str(row["id"]),
            "gameId": str(row["game_id"]) if row["game_id"] else None,
            "title": row["title"],
            "status": row["status"],
            "latestRunId": str(row["latest_run_id"]) if row["latest_run_id"] else None,
            "latestRunStatus": row["latest_run_status"],
            "createdAt": row["created_at"],
            "updatedAt": row["updated_at"],
        }
        for row in rows
    ]


def get_project(user_id: str, project_id: str) -> dict[str, Any] | None:
    ensure_agent_framework_schema()
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT id, game_id, title, status, metadata, created_at, updated_at
FROM agent_projects
WHERE id = %s AND user_id = %s
LIMIT 1
""",
            (project_id, user_id),
        ).fetchone()
    if not row:
        return None
    return {
        "projectId": str(row["id"]),
        "gameId": str(row["game_id"]) if row["game_id"] else None,
        "title": row["title"],
        "status": row["status"],
        "metadata": row["metadata"],
        "createdAt": row["created_at"],
        "updatedAt": row["updated_at"],
    }


def get_run(user_id: str, run_id: str) -> dict[str, Any] | None:
    ensure_agent_framework_schema()
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT r.*
FROM create_runs r
WHERE r.id = %s AND r.user_id = %s
LIMIT 1
""",
            (run_id, user_id),
        ).fetchone()
    if not row:
        return None
    return {
        "runId": str(row["id"]),
        "taskId": str(row["task_id"]),
        "projectId": str(row["project_id"]),
        "jobId": str(row["job_id"]) if row["job_id"] else None,
        "gameId": str(row["game_id"]) if row["game_id"] else None,
        "versionId": str(row["version_id"]) if row["version_id"] else None,
        "createType": row["create_type"],
        "agentMode": row["agent_mode"],
        "status": row["status"],
        "summary": row["summary"],
        "logObjectKey": row["log_object_key"],
        "startedAt": row["started_at"],
        "completedAt": row["completed_at"],
    }


def get_run_steps(user_id: str, run_id: str) -> list[dict[str, Any]] | None:
    ensure_agent_framework_schema()
    if not get_run(user_id, run_id):
        return None
    with db_connection() as connection:
        rows = connection.execute(
            """
SELECT step_no, stage, status, input_summary, output_summary, metrics, created_at
FROM create_run_steps
WHERE run_id = %s
ORDER BY step_no
""",
            (run_id,),
        ).fetchall()
    return [
        {
            "stepNo": row["step_no"],
            "stage": row["stage"],
            "status": row["status"],
            "inputSummary": row["input_summary"],
            "outputSummary": row["output_summary"],
            "metrics": row["metrics"],
            "createdAt": row["created_at"],
        }
        for row in rows
    ]


def get_agent_state_for_job(user_id: str, job_id: str) -> dict[str, Any] | None:
    ensure_agent_framework_schema()
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT id, task_id, project_id, log_object_key, summary, status
FROM create_runs
WHERE job_id = %s AND user_id = %s
ORDER BY created_at DESC
LIMIT 1
""",
            (job_id, user_id),
        ).fetchone()
    if not row:
        return None
    run_id = str(row["id"])
    return {
        "run": {
            "runId": run_id,
            "taskId": str(row["task_id"]),
            "projectId": str(row["project_id"]),
            "status": row["status"],
            "summary": row["summary"],
            "logObjectKey": row["log_object_key"],
        },
        "taskState": TaskStateStore().summary(run_id),
        "workspace": WorktreeManager().status(run_id),
        "steps": get_run_steps(user_id, run_id) or [],
    }
