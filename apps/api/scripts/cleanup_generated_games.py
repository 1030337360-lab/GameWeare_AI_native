from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

from minio import Minio
import redis

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import db_connection


CREATE_REDIS_PREFIXES = (
    "create:recent-game:",
    "create:run-events:",
    "agent:long:",
    "agent:short:",
)


def minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )


def redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def fetch_cleanup_targets() -> dict[str, Any]:
    with db_connection() as connection:
        games = connection.execute(
            """
SELECT DISTINCT g.id, g.slug, g.title
FROM games g
LEFT JOIN game_versions gv ON gv.game_id = g.id
LEFT JOIN generation_jobs gj ON gj.id = gv.source_job_id OR gj.game_id = g.id
WHERE
  gj.id IS NOT NULL
  OR g.metadata->>'createdBy' IN ('static-create', 'llm-create')
ORDER BY g.slug
"""
        ).fetchall()
        game_ids = [row["id"] for row in games]
        jobs = connection.execute(
            """
SELECT DISTINCT id
FROM generation_jobs
WHERE game_id = ANY(%s)
   OR id IN (
     SELECT source_job_id
     FROM game_versions
     WHERE game_id = ANY(%s) AND source_job_id IS NOT NULL
   )
""",
            (game_ids or [], game_ids or []),
        ).fetchall()
        job_ids = [row["id"] for row in jobs]
        runs = connection.execute(
            """
SELECT id, project_id
FROM create_runs
WHERE job_id = ANY(%s)
   OR game_id = ANY(%s)
""",
            (job_ids or [], game_ids or []),
        ).fetchall()
        run_ids = [row["id"] for row in runs]
        project_ids = list({row["project_id"] for row in runs})
        assets = connection.execute(
            """
SELECT id, bucket, object_key
FROM assets
WHERE game_id = ANY(%s)
   OR job_id = ANY(%s)
ORDER BY object_key
""",
            (game_ids or [], job_ids or []),
        ).fetchall()
    return {
        "games": games,
        "game_ids": game_ids,
        "job_ids": job_ids,
        "run_ids": run_ids,
        "project_ids": project_ids,
        "assets": assets,
    }


def redis_keys_for_cleanup() -> list[str]:
    client = redis_client()
    keys: list[str] = []
    for prefix in CREATE_REDIS_PREFIXES:
        keys.extend(client.keys(f"{prefix}*"))
    return sorted(set(keys))


def print_summary(targets: dict[str, Any], redis_keys: list[str]) -> None:
    print("Generated game cleanup summary")
    print(f"- games: {len(targets['games'])}")
    for row in targets["games"]:
        print(f"  - {row['slug']} ({row['id']}) {row['title']}")
    print(f"- generation_jobs: {len(targets['job_ids'])}")
    print(f"- create_runs: {len(targets['run_ids'])}")
    print(f"- agent_projects: {len(targets['project_ids'])}")
    print(f"- assets / MinIO objects: {len(targets['assets'])}")
    print(f"- redis keys: {len(redis_keys)}")


def delete_minio_objects(assets: list[dict[str, Any]]) -> None:
    if not assets:
        return
    client = minio_client()
    for asset in assets:
        client.remove_object(asset["bucket"], asset["object_key"])


def delete_redis_keys(keys: list[str]) -> None:
    if keys:
        redis_client().delete(*keys)


def delete_sql_records(targets: dict[str, Any]) -> None:
    game_ids = targets["game_ids"]
    job_ids = targets["job_ids"]
    run_ids = targets["run_ids"]
    project_ids = targets["project_ids"]
    with db_connection() as connection:
        with connection.transaction():
            connection.execute("DELETE FROM game_likes WHERE game_id = ANY(%s)", (game_ids,))
            connection.execute("DELETE FROM game_favorites WHERE game_id = ANY(%s)", (game_ids,))
            connection.execute("DELETE FROM game_comments WHERE game_id = ANY(%s)", (game_ids,))
            connection.execute("DELETE FROM play_events WHERE game_id = ANY(%s)", (game_ids,))
            connection.execute("DELETE FROM job_artifacts WHERE job_id = ANY(%s)", (job_ids,))
            connection.execute("DELETE FROM assets WHERE game_id = ANY(%s) OR job_id = ANY(%s)", (game_ids, job_ids))
            connection.execute("UPDATE games SET current_version_id = NULL, cover_asset_id = NULL WHERE id = ANY(%s)", (game_ids,))
            connection.execute("DELETE FROM game_tags WHERE game_id = ANY(%s)", (game_ids,))
            connection.execute("DELETE FROM game_versions WHERE game_id = ANY(%s)", (game_ids,))
            connection.execute("DELETE FROM agent_task_state_index WHERE run_id = ANY(%s)", (run_ids,))
            connection.execute("DELETE FROM create_run_steps WHERE run_id = ANY(%s)", (run_ids,))
            connection.execute("DELETE FROM agent_workspace_runs WHERE run_id = ANY(%s)", (run_ids,))
            connection.execute("DELETE FROM create_runs WHERE id = ANY(%s)", (run_ids,))
            connection.execute("DELETE FROM agent_memory_index WHERE project_id = ANY(%s)", (project_ids,))
            connection.execute("DELETE FROM agent_projects WHERE id = ANY(%s)", (project_ids,))
            connection.execute("DELETE FROM generation_jobs WHERE id = ANY(%s)", (job_ids,))
            connection.execute("DELETE FROM games WHERE id = ANY(%s)", (game_ids,))


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean generated Create test games without touching seed/static games.")
    parser.add_argument("--apply", action="store_true", help="Actually delete SQL, MinIO, and Redis records.")
    args = parser.parse_args()

    targets = fetch_cleanup_targets()
    redis_keys = redis_keys_for_cleanup()
    print_summary(targets, redis_keys)

    if not args.apply:
        print("Dry run only. Re-run with --apply to delete these generated records.")
        return 0

    delete_minio_objects(targets["assets"])
    delete_sql_records(targets)
    delete_redis_keys(redis_keys)
    print("Cleanup applied.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
