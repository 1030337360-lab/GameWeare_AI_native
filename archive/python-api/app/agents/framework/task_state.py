from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from app.database import db_connection
from app.agents.framework.storage import put_json_object


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class TaskState:
    run_id: str
    task_id: str
    project_id: str
    user_id: str
    user_request: str
    status: str = "running"
    attempts: int = 1
    step_reason: str = "create_requested"
    final_answer: str | None = None
    checkpoint: dict[str, Any] = field(default_factory=dict)
    resume_status: str = "fresh"

    def model_dump(self) -> dict[str, Any]:
        return {
            "runId": self.run_id,
            "taskId": self.task_id,
            "projectId": self.project_id,
            "userId": self.user_id,
            "userRequest": self.user_request,
            "status": self.status,
            "attempts": self.attempts,
            "stepReason": self.step_reason,
            "finalAnswer": self.final_answer,
            "checkpoint": self.checkpoint,
            "resumeStatus": self.resume_status,
            "updatedAt": _now_iso(),
        }


class TaskStateStore:
    def object_key(self, run_id: str) -> str:
        return f"agent-runs/{run_id}/task-state.json"

    def save(self, state: TaskState, latest_log_object_key: str) -> str:
        object_key = self.object_key(state.run_id)
        put_json_object(object_key, state.model_dump())
        with db_connection() as connection:
            connection.execute(
                """
INSERT INTO agent_task_state_index (
  run_id, task_id, project_id, user_id, status, checkpoint_object_key, latest_log_object_key, resume_status
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (run_id) DO UPDATE SET
  status = EXCLUDED.status,
  checkpoint_object_key = EXCLUDED.checkpoint_object_key,
  latest_log_object_key = EXCLUDED.latest_log_object_key,
  resume_status = EXCLUDED.resume_status,
  updated_at = now()
""",
                (
                    state.run_id,
                    state.task_id,
                    state.project_id,
                    state.user_id,
                    state.status,
                    object_key,
                    latest_log_object_key,
                    state.resume_status,
                ),
            )
        return object_key

    def checkpoint(self, state: TaskState, label: str, payload: dict[str, Any], latest_log_object_key: str) -> str:
        state.checkpoint = {"label": label, "payload": payload, "createdAt": _now_iso()}
        state.step_reason = label
        return self.save(state, latest_log_object_key)

    def summary(self, run_id: str) -> dict[str, Any] | None:
        with db_connection() as connection:
            row = connection.execute(
                """
SELECT run_id, task_id, project_id, status, checkpoint_object_key, latest_log_object_key, resume_status, updated_at
FROM agent_task_state_index
WHERE run_id = %s
LIMIT 1
""",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "runId": str(row["run_id"]),
            "taskId": str(row["task_id"]),
            "projectId": str(row["project_id"]),
            "status": row["status"],
            "checkpointObjectKey": row["checkpoint_object_key"],
            "latestLogObjectKey": row["latest_log_object_key"],
            "resumeStatus": row["resume_status"],
            "updatedAt": row["updated_at"],
        }
