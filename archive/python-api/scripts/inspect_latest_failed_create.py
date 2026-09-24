from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import db_connection


SENSITIVE_KEYS = {"apikey", "api_key", "token", "secret", "authorization", "password", "access_token", "refresh_token"}
SECRET_PATTERN = re.compile(r"\b(?:sk|pk|rk)-[A-Za-z0-9_\-]{8,}\b")


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def json_default(value: Any) -> str | int | float | None:
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


def redact(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: "[redacted]" if str(key).replace("-", "_").lower() in SENSITIVE_KEYS else redact(item)
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [redact(item) for item in value]
    if isinstance(value, str):
        redacted = SECRET_PATTERN.sub("[redacted]", value)
        try:
            parsed = json.loads(redacted)
        except json.JSONDecodeError:
            return redacted
        return json.dumps(redact(parsed), ensure_ascii=False)
    return value


def fetch_latest_failed_job() -> dict[str, Any] | None:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT
  gj.*,
  u.email AS creator_email,
  u.display_name AS creator_display_name,
  g.slug AS game_slug,
  g.title AS game_title
FROM generation_jobs gj
LEFT JOIN users u ON u.id = gj.creator_id
LEFT JOIN games g ON g.id = gj.game_id
WHERE gj.status = 'failed'
ORDER BY COALESCE(gj.completed_at, gj.updated_at, gj.created_at) DESC
LIMIT 1
"""
        ).fetchone()


def fetch_runs_for_job(job_id: str) -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT
  r.*,
  p.title AS project_title,
  p.status AS project_status,
  p.metadata AS project_metadata
FROM create_runs r
LEFT JOIN agent_projects p ON p.id = r.project_id
WHERE r.job_id = %s OR r.status = 'failed'
ORDER BY
  CASE WHEN r.job_id = %s THEN 0 ELSE 1 END,
  COALESCE(r.completed_at, r.updated_at, r.created_at) DESC
LIMIT 10
""",
            (job_id, job_id),
        ).fetchall()


def fetch_run_steps(run_id: str) -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT *
FROM create_run_steps
WHERE run_id = %s
ORDER BY step_no
""",
            (run_id,),
        ).fetchall()


def fetch_agent_runs(job_id: str) -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT *
FROM agent_runs
WHERE job_id = %s
ORDER BY created_at
""",
            (job_id,),
        ).fetchall()


def fetch_task_state(run_id: str) -> dict[str, Any] | None:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT *
FROM agent_task_state_index
WHERE run_id = %s
LIMIT 1
""",
            (run_id,),
        ).fetchone()


def fetch_workspace(run_id: str) -> dict[str, Any] | None:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT *
FROM agent_workspace_runs
WHERE run_id = %s
LIMIT 1
""",
            (run_id,),
        ).fetchone()


def fetch_assets(job_id: str) -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT id, kind, bucket, object_key, public_url, content_type, size_bytes, sha256, created_at
FROM assets
WHERE job_id = %s
ORDER BY created_at, kind, object_key
""",
            (job_id,),
        ).fetchall()


def fetch_job_artifacts(job_id: str) -> list[dict[str, Any]]:
    with db_connection() as connection:
        return connection.execute(
            """
SELECT
  ja.purpose,
  a.id,
  a.kind,
  a.bucket,
  a.object_key,
  a.public_url,
  a.content_type,
  a.size_bytes,
  a.sha256,
  a.created_at
FROM job_artifacts ja
JOIN assets a ON a.id = ja.asset_id
WHERE ja.job_id = %s
ORDER BY a.created_at, ja.purpose
""",
            (job_id,),
        ).fetchall()


def redis_value_preview(client: redis.Redis, key: str, limit: int = 2000) -> Any:
    key_type = client.type(key)
    if key_type == "none":
        return None
    if key_type == "string":
        value = redact(client.get(key))
        if isinstance(value, str) and len(value) > limit:
            return value[:limit] + "...[truncated]"
        return value
    if key_type == "list":
        values = [redact(value) for value in client.lrange(key, 0, -1)]
        return [value[:limit] + "...[truncated]" if len(value) > limit else value for value in values]
    if key_type == "hash":
        values = {name: redact(value) for name, value in client.hgetall(key).items()}
        return {
            name: value[:limit] + "...[truncated]" if len(value) > limit else value
            for name, value in values.items()
        }
    if key_type == "set":
        return sorted(client.smembers(key))
    if key_type == "zset":
        return client.zrange(key, 0, -1, withscores=True)
    return f"<unsupported redis type: {key_type}>"


def fetch_redis_diagnostics(run_ids: list[str], user_id: str | None, project_ids: list[str]) -> dict[str, Any]:
    client = redis_client()
    patterns = []
    for run_id in run_ids:
        patterns.extend(
            [
                f"create:run-events:{run_id}*",
                f"agent:short:{run_id}:*",
            ]
        )
    if user_id:
        patterns.append(f"create:recent-game:{user_id}")
        patterns.append(f"create:ai-config:{user_id}:*")
        for project_id in project_ids:
            patterns.append(f"agent:long:*:{project_id}:*")

    keys: list[str] = []
    for pattern in patterns:
        keys.extend(client.keys(pattern))

    diagnostics: dict[str, Any] = {}
    for key in sorted(set(keys)):
        diagnostics[key] = {
            "type": client.type(key),
            "ttl": client.ttl(key),
            "value": redis_value_preview(client, key),
        }
    return diagnostics


def collect_latest_failed_create() -> dict[str, Any]:
    job = fetch_latest_failed_job()
    if not job:
        return {"found": False, "message": "No failed generation_jobs row was found."}

    job_id = str(job["id"])
    runs = fetch_runs_for_job(job_id)
    selected_runs = [run for run in runs if str(run.get("job_id")) == job_id] or runs[:1]
    run_ids = [str(run["id"]) for run in selected_runs]
    project_ids = sorted({str(run["project_id"]) for run in selected_runs if run.get("project_id")})

    return {
        "found": True,
        "job": job,
        "runs": [
            {
                **run,
                "steps": fetch_run_steps(str(run["id"])),
                "taskState": fetch_task_state(str(run["id"])),
                "workspace": fetch_workspace(str(run["id"])),
            }
            for run in selected_runs
        ],
        "otherFailedRunsConsidered": [
            run for run in runs if str(run["id"]) not in set(run_ids)
        ],
        "agentRuns": fetch_agent_runs(job_id),
        "assets": fetch_assets(job_id),
        "jobArtifacts": fetch_job_artifacts(job_id),
        "redis": fetch_redis_diagnostics(run_ids, str(job["creator_id"]) if job.get("creator_id") else None, project_ids),
    }


def print_section(title: str) -> None:
    print()
    print(f"== {title} ==")


def dump_mapping(value: dict[str, Any], *, indent: int = 0) -> None:
    prefix = " " * indent
    for key, item in value.items():
        print(f"{prefix}{key}: {json.dumps(item, ensure_ascii=False, default=json_default)}")


def print_report(report: dict[str, Any]) -> None:
    if not report.get("found"):
        print(report["message"])
        return

    job = report["job"]
    print_section("Latest Failed Create Job")
    dump_mapping(
        {
            "id": job["id"],
            "status": job["status"],
            "current_stage": job["current_stage"],
            "error_code": job["error_code"],
            "error_message": job["error_message"],
            "created_at": job["created_at"],
            "updated_at": job["updated_at"],
            "started_at": job["started_at"],
            "completed_at": job["completed_at"],
            "creator_id": job["creator_id"],
            "creator_email": job["creator_email"],
            "creator_display_name": job["creator_display_name"],
            "game_id": job["game_id"],
            "game_slug": job["game_slug"],
            "game_title": job["game_title"],
            "version_id": job["version_id"],
            "input_payload": job["input_payload"],
            "prompt": job["prompt"],
        }
    )

    print_section("Create Runs")
    for run in report["runs"]:
        dump_mapping(
            {
                "run_id": run["id"],
                "task_id": run["task_id"],
                "project_id": run["project_id"],
                "project_title": run["project_title"],
                "create_type": run["create_type"],
                "agent_mode": run["agent_mode"],
                "status": run["status"],
                "summary": run["summary"],
                "log_object_key": run["log_object_key"],
                "started_at": run["started_at"],
                "completed_at": run["completed_at"],
                "updated_at": run["updated_at"],
            },
            indent=2,
        )
        print("  steps:")
        for step in run["steps"]:
            print(
                "    "
                + json.dumps(
                    {
                        "stepNo": step["step_no"],
                        "stage": step["stage"],
                        "status": step["status"],
                        "input": step["input_summary"],
                        "output": step["output_summary"],
                        "metrics": step["metrics"],
                        "createdAt": step["created_at"],
                    },
                    ensure_ascii=False,
                    default=json_default,
                )
            )
        print("  task_state:")
        print("    " + json.dumps(run["taskState"], ensure_ascii=False, default=json_default))
        print("  workspace:")
        print("    " + json.dumps(run["workspace"], ensure_ascii=False, default=json_default))

    print_section("Legacy Agent Runs")
    for record in report["agentRuns"]:
        print(json.dumps(record, ensure_ascii=False, default=json_default))

    print_section("Assets")
    for asset in report["assets"]:
        print(json.dumps(asset, ensure_ascii=False, default=json_default))

    print_section("Job Artifacts")
    for artifact in report["jobArtifacts"]:
        print(json.dumps(artifact, ensure_ascii=False, default=json_default))

    print_section("Redis Diagnostics")
    if not report["redis"]:
        print("No matching Redis keys found.")
    for key, payload in report["redis"].items():
        print(f"{key}: {json.dumps(payload, ensure_ascii=False, default=json_default)}")

    if report["otherFailedRunsConsidered"]:
        print_section("Other Failed Runs Considered")
        for run in report["otherFailedRunsConsidered"]:
            print(json.dumps(run, ensure_ascii=False, default=json_default))


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect the latest failed Create job and its related run diagnostics.")
    parser.add_argument("--json", action="store_true", help="Print the full report as JSON.")
    args = parser.parse_args()

    report = collect_latest_failed_create()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, default=json_default))
    else:
        print_report(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
