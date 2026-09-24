from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

import redis
from minio import Minio
from minio.error import S3Error

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.config import get_settings
from app.database import db_connection


TEST_EMAIL_LIKE_PATTERNS = (
    "smoke-%@gameweare.local",
    "llm-%@gameweare.local",
    "decentralized-%@gameweare.local",
    "workspace-%@gameweare.local",
    "multi-agent-%@gameweare.local",
    "dbg-%@gameweare.local",
    "maintainer-test%@gameweare.local",
)

TEST_OBJECT_LIKE_PATTERNS = (
    "maintenance-smoke/%",
)

REDIS_ID_SCANNED_PREFIXES = (
    "agent:long:*",
    "agent:short:*",
    "create:run-events:*",
    "create:plan-approval:*",
    "create:decentralized:preview:*",
    "create:decentralized:selection:*",
    "create:input-assets:*",
)

PLAY_STATS_HASH_KEYS = ("play:pending-counts", "play:realtime-counts")


def _ids(rows: list[dict[str, Any]], key: str = "id") -> set[str]:
    return {str(row[key]) for row in rows if row.get(key)}


def _rows(connection: Any, query: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(query, params).fetchall()]


def _select_ids(connection: Any, query: str, params: tuple[Any, ...]) -> set[str]:
    return _ids(_rows(connection, query, params))


def _uuid_any(values: set[str]) -> list[UUID]:
    return [UUID(value) for value in sorted(values)]


def _expand_targets(connection: Any, targets: dict[str, Any]) -> None:
    user_ids: set[str] = targets["user_ids"]
    project_ids: set[str] = targets["project_ids"]
    run_ids: set[str] = targets["run_ids"]
    job_ids: set[str] = targets["job_ids"]
    game_ids: set[str] = targets["game_ids"]
    version_ids: set[str] = targets["version_ids"]

    for _ in range(4):
        before = tuple(len(values) for values in (project_ids, run_ids, job_ids, game_ids, version_ids))

        if user_ids:
            project_ids.update(
                _select_ids(
                    connection,
                    "SELECT id FROM agent_projects WHERE user_id = ANY(%s)",
                    (_uuid_any(user_ids),),
                )
            )
            job_ids.update(
                _select_ids(
                    connection,
                    "SELECT id FROM generation_jobs WHERE creator_id = ANY(%s)",
                    (_uuid_any(user_ids),),
                )
            )
            game_ids.update(
                _select_ids(
                    connection,
                    "SELECT id FROM games WHERE author_id = ANY(%s)",
                    (_uuid_any(user_ids),),
                )
            )

        run_clauses: list[str] = []
        run_params: list[Any] = []
        if user_ids:
            run_clauses.append("user_id = ANY(%s)")
            run_params.append(_uuid_any(user_ids))
        if project_ids:
            run_clauses.append("project_id = ANY(%s)")
            run_params.append(_uuid_any(project_ids))
        if job_ids:
            run_clauses.append("job_id = ANY(%s)")
            run_params.append(_uuid_any(job_ids))
        if game_ids:
            run_clauses.append("game_id = ANY(%s)")
            run_params.append(_uuid_any(game_ids))
        if version_ids:
            run_clauses.append("version_id = ANY(%s)")
            run_params.append(_uuid_any(version_ids))
        if run_clauses:
            run_rows = _rows(
                connection,
                f"""
SELECT id, project_id, job_id, game_id, version_id, log_object_key
FROM create_runs
WHERE {" OR ".join(run_clauses)}
""",
                tuple(run_params),
            )
            run_ids.update(_ids(run_rows))
            project_ids.update(str(row["project_id"]) for row in run_rows if row.get("project_id"))
            job_ids.update(str(row["job_id"]) for row in run_rows if row.get("job_id"))
            game_ids.update(str(row["game_id"]) for row in run_rows if row.get("game_id"))
            version_ids.update(str(row["version_id"]) for row in run_rows if row.get("version_id"))

        if job_ids or game_ids or version_ids:
            job_clauses: list[str] = []
            job_params: list[Any] = []
            if job_ids:
                job_clauses.append("id = ANY(%s)")
                job_params.append(_uuid_any(job_ids))
            if game_ids:
                job_clauses.append("game_id = ANY(%s)")
                job_params.append(_uuid_any(game_ids))
            if version_ids:
                job_clauses.append("version_id = ANY(%s)")
                job_params.append(_uuid_any(version_ids))
            job_rows = _rows(
                connection,
                f"SELECT id, game_id, version_id FROM generation_jobs WHERE {' OR '.join(job_clauses)}",
                tuple(job_params),
            )
            job_ids.update(_ids(job_rows))
            game_ids.update(str(row["game_id"]) for row in job_rows if row.get("game_id"))
            version_ids.update(str(row["version_id"]) for row in job_rows if row.get("version_id"))

        if game_ids or version_ids or job_ids:
            version_clauses: list[str] = []
            version_params: list[Any] = []
            if version_ids:
                version_clauses.append("id = ANY(%s)")
                version_params.append(_uuid_any(version_ids))
            if game_ids:
                version_clauses.append("game_id = ANY(%s)")
                version_params.append(_uuid_any(game_ids))
            if job_ids:
                version_clauses.append("source_job_id = ANY(%s)")
                version_params.append(_uuid_any(job_ids))
            version_rows = _rows(
                connection,
                f"SELECT id, game_id, source_job_id FROM game_versions WHERE {' OR '.join(version_clauses)}",
                tuple(version_params),
            )
            version_ids.update(_ids(version_rows))
            game_ids.update(str(row["game_id"]) for row in version_rows if row.get("game_id"))
            job_ids.update(str(row["source_job_id"]) for row in version_rows if row.get("source_job_id"))

        if tuple(len(values) for values in (project_ids, run_ids, job_ids, game_ids, version_ids)) == before:
            break


def fetch_cleanup_targets() -> dict[str, Any]:
    targets: dict[str, Any] = {
        "users": [],
        "user_ids": set(),
        "project_ids": set(),
        "run_ids": set(),
        "job_ids": set(),
        "game_ids": set(),
        "version_ids": set(),
        "asset_ids": set(),
        "agent_run_ids": set(),
        "interaction_game_ids": set(),
        "assets": [],
        "memory_objects": [],
        "run_objects": [],
    }

    with db_connection() as connection:
        users = _rows(
            connection,
            """
SELECT id, email
FROM users
WHERE lower(email::text) LIKE ANY(%s)
ORDER BY email
""",
            ([pattern.lower() for pattern in TEST_EMAIL_LIKE_PATTERNS],),
        )
        targets["users"] = users
        targets["user_ids"] = _ids(users)

        _expand_targets(connection, targets)

        if targets["user_ids"]:
            targets["interaction_game_ids"].update(
                _select_ids(
                    connection,
                    "SELECT DISTINCT game_id AS id FROM game_likes WHERE user_id = ANY(%s)",
                    (_uuid_any(targets["user_ids"]),),
                )
            )
            targets["interaction_game_ids"].update(
                _select_ids(
                    connection,
                    "SELECT DISTINCT game_id AS id FROM game_favorites WHERE user_id = ANY(%s)",
                    (_uuid_any(targets["user_ids"]),),
                )
            )
            targets["interaction_game_ids"].update(
                _select_ids(
                    connection,
                    "SELECT DISTINCT game_id AS id FROM game_comments WHERE user_id = ANY(%s)",
                    (_uuid_any(targets["user_ids"]),),
                )
            )
            targets["interaction_game_ids"].update(
                _select_ids(
                    connection,
                    "SELECT DISTINCT game_id AS id FROM play_events WHERE user_id = ANY(%s)",
                    (_uuid_any(targets["user_ids"]),),
                )
            )

        asset_clauses: list[str] = []
        asset_params: list[Any] = []
        if targets["user_ids"]:
            asset_clauses.append("owner_id = ANY(%s)")
            asset_params.append(_uuid_any(targets["user_ids"]))
        if targets["game_ids"]:
            asset_clauses.append("game_id = ANY(%s)")
            asset_params.append(_uuid_any(targets["game_ids"]))
        if targets["version_ids"]:
            asset_clauses.append("version_id = ANY(%s)")
            asset_params.append(_uuid_any(targets["version_ids"]))
        if targets["job_ids"]:
            asset_clauses.append("job_id = ANY(%s)")
            asset_params.append(_uuid_any(targets["job_ids"]))
        asset_clauses.append("object_key LIKE ANY(%s)")
        asset_params.append(list(TEST_OBJECT_LIKE_PATTERNS))
        assets = _rows(
            connection,
            f"""
SELECT id, bucket, object_key
FROM assets
WHERE {" OR ".join(asset_clauses)}
ORDER BY object_key
""",
            tuple(asset_params),
        )
        targets["assets"] = assets
        targets["asset_ids"] = _ids(assets)

        if targets["job_ids"]:
            targets["agent_run_ids"] = _select_ids(
                connection,
                "SELECT id FROM agent_runs WHERE job_id = ANY(%s)",
                (_uuid_any(targets["job_ids"]),),
            )

        run_objects = []
        if targets["run_ids"]:
            run_objects = _rows(
                connection,
                """
SELECT log_object_key AS object_key
FROM create_runs
WHERE id = ANY(%s) AND log_object_key IS NOT NULL
UNION
SELECT checkpoint_object_key AS object_key
FROM agent_task_state_index
WHERE run_id = ANY(%s)
UNION
SELECT latest_log_object_key AS object_key
FROM agent_task_state_index
WHERE run_id = ANY(%s)
""",
                (_uuid_any(targets["run_ids"]), _uuid_any(targets["run_ids"]), _uuid_any(targets["run_ids"])),
            )
            for run_id in targets["run_ids"]:
                run_objects.append({"object_key": f"agent-runs/{run_id}/run-log.jsonl"})
                run_objects.append({"object_key": f"agent-runs/{run_id}/task-state.json"})
        targets["run_objects"] = run_objects

        memory_clauses: list[str] = []
        memory_params: list[Any] = []
        if targets["user_ids"]:
            memory_clauses.append("user_id = ANY(%s)")
            memory_params.append(_uuid_any(targets["user_ids"]))
        if targets["project_ids"]:
            memory_clauses.append("project_id = ANY(%s)")
            memory_params.append(_uuid_any(targets["project_ids"]))
        if memory_clauses:
            targets["memory_objects"] = _rows(
                connection,
                f"""
SELECT id, bucket, object_key
FROM agent_memory_index
WHERE {" OR ".join(memory_clauses)}
ORDER BY object_key
""",
                tuple(memory_params),
            )

    return targets


def _redis_client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def fetch_redis_targets(targets: dict[str, Any]) -> dict[str, Any]:
    user_ids = set(targets["user_ids"])
    project_ids = set(targets["project_ids"])
    run_ids = set(targets["run_ids"])
    job_ids = set(targets["job_ids"])
    game_ids = set(targets["game_ids"])
    needles = user_ids | project_ids | run_ids | job_ids | game_ids
    result = {"keys": set(), "hash_fields": {key: set() for key in PLAY_STATS_HASH_KEYS}, "warnings": []}

    try:
        client = _redis_client()
        client.ping()
    except Exception as exc:
        result["warnings"].append(f"Redis unavailable: {exc}")
        return result

    def add_if_exists(key: str) -> None:
        if client.exists(key):
            result["keys"].add(key)

    for user_id in user_ids:
        for key in client.scan_iter(match=f"create:ai-config:{user_id}:*"):
            result["keys"].add(key)
        add_if_exists(f"create:recent-game:{user_id}")

    for run_id in run_ids:
        for key in (
            f"create:run-events:{run_id}",
            f"create:plan-approval:{run_id}",
            f"create:decentralized:preview:{run_id}",
            f"create:decentralized:selection:{run_id}",
        ):
            add_if_exists(key)
        for key in client.scan_iter(match=f"agent:short:{run_id}:*"):
            result["keys"].add(key)

    for job_id in job_ids:
        add_if_exists(f"create:input-assets:{job_id}")

    for pattern in REDIS_ID_SCANNED_PREFIXES:
        for key in client.scan_iter(match=pattern):
            if any(needle in key for needle in needles):
                result["keys"].add(key)

    for key in client.scan_iter(match="auth:jwt:*"):
        try:
            payload = json.loads(client.get(key) or "{}")
        except json.JSONDecodeError:
            continue
        if str(payload.get("userId")) in user_ids:
            result["keys"].add(key)

    for hash_key in PLAY_STATS_HASH_KEYS:
        try:
            fields = set(client.hkeys(hash_key))
        except redis.RedisError as exc:
            result["warnings"].append(f"Cannot inspect Redis hash {hash_key}: {exc}")
            continue
        result["hash_fields"][hash_key].update(fields & game_ids)

    return result


def minio_objects_for_cleanup(targets: dict[str, Any]) -> list[dict[str, str]]:
    settings = get_settings()
    objects: set[tuple[str, str]] = set()
    for asset in targets["assets"]:
        bucket = str(asset.get("bucket") or "")
        object_key = str(asset.get("object_key") or "")
        if bucket and object_key and bucket != "external":
            objects.add((bucket, object_key))
    for item in targets["memory_objects"]:
        bucket = str(item.get("bucket") or settings.minio_bucket)
        object_key = str(item.get("object_key") or "")
        if bucket and object_key:
            objects.add((bucket, object_key))
    for item in targets["run_objects"]:
        object_key = str(item.get("object_key") or "")
        if object_key:
            objects.add((settings.minio_bucket, object_key))
    return [{"bucket": bucket, "object_key": object_key} for bucket, object_key in sorted(objects)]


def print_summary(targets: dict[str, Any], redis_targets: dict[str, Any]) -> None:
    minio_objects = minio_objects_for_cleanup(targets)
    print("Test pollution cleanup summary")
    print(f"- users: {len(targets['user_ids'])}")
    for row in targets["users"]:
        print(f"  - {row['email']} ({row['id']})")
    print(f"- agent_projects: {len(targets['project_ids'])}")
    print(f"- create_runs: {len(targets['run_ids'])}")
    print(f"- generation_jobs: {len(targets['job_ids'])}")
    print(f"- games: {len(targets['game_ids'])}")
    print(f"- game_versions: {len(targets['version_ids'])}")
    print(f"- assets rows: {len(targets['asset_ids'])}")
    print(f"- MinIO objects: {len(minio_objects)}")
    print(f"- Redis keys: {len(redis_targets['keys'])}")
    print(f"- Redis hash fields: {sum(len(fields) for fields in redis_targets['hash_fields'].values())}")
    if redis_targets["warnings"]:
        print("- warnings:")
        for warning in redis_targets["warnings"]:
            print(f"  - {warning}")


def _minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )


def delete_minio_objects(objects: list[dict[str, str]]) -> None:
    if not objects:
        return
    client = _minio_client()
    for item in objects:
        try:
            client.remove_object(item["bucket"], item["object_key"])
        except S3Error as exc:
            if exc.code not in {"NoSuchKey", "NoSuchBucket"}:
                raise


def delete_redis_targets(redis_targets: dict[str, Any]) -> None:
    client = _redis_client()
    keys = sorted(redis_targets["keys"])
    if keys:
        client.delete(*keys)
    for hash_key, fields in redis_targets["hash_fields"].items():
        if fields:
            client.hdel(hash_key, *sorted(fields))


def delete_sql_records(targets: dict[str, Any]) -> None:
    user_ids = _uuid_any(targets["user_ids"])
    project_ids = _uuid_any(targets["project_ids"])
    run_ids = _uuid_any(targets["run_ids"])
    job_ids = _uuid_any(targets["job_ids"])
    game_ids = _uuid_any(targets["game_ids"])
    version_ids = _uuid_any(targets["version_ids"])
    asset_ids = _uuid_any(targets["asset_ids"])
    agent_run_ids = _uuid_any(targets["agent_run_ids"])
    impacted_game_ids = _uuid_any(set(targets["interaction_game_ids"]) | set(targets["game_ids"]))

    with db_connection() as connection:
        with connection.transaction():
            moderation_target_ids = sorted(set(impacted_game_ids) | set(job_ids) | set(version_ids) | set(asset_ids))
            if moderation_target_ids:
                connection.execute(
                    """
DELETE FROM moderation_reviews
WHERE target_id = ANY(%s) AND target_type IN ('game', 'version', 'asset', 'job', 'comment')
""",
                    (moderation_target_ids,),
                )
                connection.execute(
                    """
DELETE FROM audit_logs
WHERE target_id = ANY(%s) AND target_type IN ('game', 'version', 'asset', 'job', 'comment')
""",
                    (moderation_target_ids,),
                )
            if user_ids:
                connection.execute("DELETE FROM audit_logs WHERE actor_user_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM moderation_reviews WHERE reviewer_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM play_events WHERE user_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM game_likes WHERE user_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM game_favorites WHERE user_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM game_comments WHERE user_id = ANY(%s)", (user_ids,))
            if game_ids:
                connection.execute("DELETE FROM play_events WHERE game_id = ANY(%s)", (game_ids,))
                connection.execute("DELETE FROM game_likes WHERE game_id = ANY(%s)", (game_ids,))
                connection.execute("DELETE FROM game_favorites WHERE game_id = ANY(%s)", (game_ids,))
                connection.execute("DELETE FROM game_comments WHERE game_id = ANY(%s)", (game_ids,))
                connection.execute("DELETE FROM game_tags WHERE game_id = ANY(%s)", (game_ids,))
            if job_ids or agent_run_ids:
                if job_ids:
                    connection.execute("DELETE FROM model_usage_events WHERE job_id = ANY(%s)", (job_ids,))
                if agent_run_ids:
                    connection.execute("DELETE FROM model_usage_events WHERE agent_run_id = ANY(%s)", (agent_run_ids,))
            if job_ids or asset_ids:
                if job_ids and asset_ids:
                    connection.execute("DELETE FROM job_artifacts WHERE job_id = ANY(%s) OR asset_id = ANY(%s)", (job_ids, asset_ids))
                elif job_ids:
                    connection.execute("DELETE FROM job_artifacts WHERE job_id = ANY(%s)", (job_ids,))
                elif asset_ids:
                    connection.execute("DELETE FROM job_artifacts WHERE asset_id = ANY(%s)", (asset_ids,))
            if job_ids:
                connection.execute("DELETE FROM agent_runs WHERE job_id = ANY(%s)", (job_ids,))
            if run_ids:
                connection.execute("DELETE FROM agent_task_state_index WHERE run_id = ANY(%s)", (run_ids,))
                connection.execute("DELETE FROM agent_workspace_runs WHERE run_id = ANY(%s)", (run_ids,))
                connection.execute("DELETE FROM create_run_steps WHERE run_id = ANY(%s)", (run_ids,))
            if project_ids or user_ids:
                if project_ids and user_ids:
                    connection.execute("DELETE FROM agent_memory_index WHERE project_id = ANY(%s) OR user_id = ANY(%s)", (project_ids, user_ids))
                elif project_ids:
                    connection.execute("DELETE FROM agent_memory_index WHERE project_id = ANY(%s)", (project_ids,))
                elif user_ids:
                    connection.execute("DELETE FROM agent_memory_index WHERE user_id = ANY(%s)", (user_ids,))
            if asset_ids:
                connection.execute("UPDATE games SET cover_asset_id = NULL WHERE cover_asset_id = ANY(%s)", (asset_ids,))
                connection.execute("UPDATE game_versions SET manifest_asset_id = NULL WHERE manifest_asset_id = ANY(%s)", (asset_ids,))
            if version_ids:
                connection.execute("UPDATE games SET current_version_id = NULL WHERE current_version_id = ANY(%s)", (version_ids,))
                connection.execute("UPDATE generation_jobs SET version_id = NULL WHERE version_id = ANY(%s)", (version_ids,))
            if run_ids:
                connection.execute("DELETE FROM create_runs WHERE id = ANY(%s)", (run_ids,))
            if asset_ids:
                connection.execute("DELETE FROM assets WHERE id = ANY(%s)", (asset_ids,))
            if version_ids:
                connection.execute("DELETE FROM game_versions WHERE id = ANY(%s)", (version_ids,))
            if job_ids:
                connection.execute("DELETE FROM generation_jobs WHERE id = ANY(%s)", (job_ids,))
            if project_ids:
                connection.execute("DELETE FROM agent_projects WHERE id = ANY(%s)", (project_ids,))
            if game_ids:
                connection.execute("DELETE FROM games WHERE id = ANY(%s)", (game_ids,))
            if user_ids:
                connection.execute("DELETE FROM user_ai_configs WHERE user_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM user_sessions WHERE user_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM auth_accounts WHERE user_id = ANY(%s)", (user_ids,))
                connection.execute("DELETE FROM users WHERE id = ANY(%s)", (user_ids,))
            if impacted_game_ids:
                connection.execute(
                    """
UPDATE games g
SET likes_count = COALESCE((SELECT count(*) FROM game_likes gl WHERE gl.game_id = g.id), 0)
WHERE g.id = ANY(%s)
""",
                    (impacted_game_ids,),
                )
                connection.execute(
                    """
UPDATE games g
SET favorites_count = COALESCE((SELECT count(*) FROM game_favorites gf WHERE gf.game_id = g.id), 0)
WHERE g.id = ANY(%s)
""",
                    (impacted_game_ids,),
                )


def cleanup_test_pollution(*, apply: bool = False, quiet: bool = False) -> dict[str, Any]:
    targets = fetch_cleanup_targets()
    redis_targets = fetch_redis_targets(targets)
    minio_objects = minio_objects_for_cleanup(targets)
    if not quiet:
        print_summary(targets, redis_targets)
    if not apply:
        return {"targets": targets, "redis": redis_targets, "minioObjects": minio_objects}

    delete_minio_objects(minio_objects)
    delete_sql_records(targets)
    delete_redis_targets(redis_targets)
    if not quiet:
        print("Cleanup applied.")
    return {"targets": targets, "redis": redis_targets, "minioObjects": minio_objects}


def main() -> int:
    parser = argparse.ArgumentParser(description="Clean only test-owned Gameweare SQL, MinIO, and Redis pollution.")
    parser.add_argument("--apply", action="store_true", help="Actually delete the dry-run targets.")
    args = parser.parse_args()
    cleanup_test_pollution(apply=args.apply)
    if not args.apply:
        print("Dry run only. Re-run with --apply after reviewing the target list.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
