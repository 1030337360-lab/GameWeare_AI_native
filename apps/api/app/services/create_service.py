from typing import Any

from app.database import db_connection
from app.schemas import AgentLog, CreateJob


def _job_from_row(row: dict[str, Any], logs: list[dict[str, Any]]) -> CreateJob:
    return CreateJob(
        id=str(row["id"]),
        status=row["status"],
        prompt=row["prompt"],
        createdAt=row["created_at"],
        logs=[
            AgentLog(
                stage=log["stage"],
                status=log["status"],
                message=log["output_summary"] or log["input_summary"] or "",
            )
            for log in logs
        ],
    )


def create_generation_job(creator_id: str, prompt: str, files: list[str]) -> CreateJob:
    with db_connection() as connection:
        job = connection.execute(
            """
INSERT INTO generation_jobs (creator_id, prompt, input_payload, status, current_stage)
VALUES (%s, %s, jsonb_build_object('files', %s::text[]), 'pending', 'create')
RETURNING id, status, prompt, created_at
""",
            (creator_id, prompt, files),
        ).fetchone()
        log = connection.execute(
            """
INSERT INTO agent_runs (job_id, stage, status, input_summary, output_summary, log, completed_at)
VALUES (
  %s,
  'create',
  'skipped',
  'Create job persisted to PostgreSQL.',
  'Agent execution is not wired yet; database contract is ready.',
  '{"stubbed": true}'::jsonb,
  now()
)
RETURNING stage, status, input_summary, output_summary
""",
            (job["id"],),
        ).fetchone()
    return _job_from_row(job, [log])


def get_generation_job(job_id: str) -> CreateJob | None:
    with db_connection() as connection:
        job = connection.execute(
            """
SELECT id, status, prompt, created_at
FROM generation_jobs
WHERE id = %s
LIMIT 1
""",
            (job_id,),
        ).fetchone()
        if not job:
            return None
        logs = connection.execute(
            """
SELECT stage, status, input_summary, output_summary
FROM agent_runs
WHERE job_id = %s
ORDER BY created_at
""",
            (job_id,),
        ).fetchall()
    return _job_from_row(job, logs)
