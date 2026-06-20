from __future__ import annotations

from typing import Any

from fastapi import Depends, HTTPException, status
from minio import Minio
from psycopg.types.json import Jsonb

from app.config import get_settings
from app.database import db_connection
from app.schemas import (
    CreateJob,
    MaintenanceAsset,
    MaintenanceCreateRun,
    MaintenanceGame,
    MaintenanceGameUpdateRequest,
    MaintenanceJob,
    MaintenanceModerationRequest,
    MaintenanceOverview,
    MaintenanceReview,
    MaintenanceRunStep,
    UserProfile,
)
from app.services.auth_service import hash_password, require_user
from app.services.create_service import create_generation_job_start


def _maintainer_email() -> str:
    return get_settings().maintainer_email.strip().lower()


def bootstrap_maintainer_account() -> None:
    settings = get_settings()
    email = settings.maintainer_email.strip().lower()
    password = settings.maintainer_password
    if not email or not password:
        return

    display_name = settings.maintainer_display_name.strip() or "Platform Maintainer"
    password_hash = hash_password(password)
    with db_connection() as connection:
        user = connection.execute(
            """
INSERT INTO users (email, display_name, role, status)
VALUES (%s, %s, 'admin', 'active')
ON CONFLICT (email) DO UPDATE SET
  display_name = EXCLUDED.display_name,
  role = 'admin',
  status = 'active',
  updated_at = now()
RETURNING id
""",
            (email, display_name),
        ).fetchone()
        auth_account = connection.execute(
            """
SELECT id
FROM auth_accounts
WHERE provider = 'email' AND provider_email = %s
LIMIT 1
""",
            (email,),
        ).fetchone()
        if auth_account:
            connection.execute(
                """
UPDATE auth_accounts
SET user_id = %s, password_hash = %s, updated_at = now()
WHERE id = %s
""",
                (user["id"], password_hash, auth_account["id"]),
            )
        else:
            connection.execute(
                """
INSERT INTO auth_accounts (user_id, provider, provider_user_id, provider_email, password_hash)
VALUES (%s, 'email', %s, %s, %s)
""",
                (user["id"], email, email, password_hash),
            )


def require_maintainer(user: UserProfile = Depends(require_user)) -> UserProfile:
    configured_email = _maintainer_email()
    if configured_email:
        if (user.email or "").lower() != configured_email:
            raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Configured maintainer account required")
        return user
    if user.role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Maintainer access required")
    return user


def maintenance_overview() -> MaintenanceOverview:
    with db_connection() as connection:
        job_counts_rows = connection.execute(
            "SELECT status, count(*) AS count FROM generation_jobs GROUP BY status"
        ).fetchall()
        failed_24h = connection.execute(
            """
SELECT count(*) AS count
FROM generation_jobs
WHERE status = 'failed' AND updated_at >= now() - interval '24 hours'
"""
        ).fetchone()["count"]
        pending_reviews = connection.execute(
            "SELECT count(*) AS count FROM moderation_reviews WHERE status = 'pending'"
        ).fetchone()["count"]
        public_games = connection.execute(
            """
SELECT count(*) AS count
FROM games
WHERE visibility = 'public' AND publish_status = 'published' AND deleted_at IS NULL
"""
        ).fetchone()["count"]
        asset_stats = connection.execute(
            "SELECT count(*) AS count, COALESCE(sum(size_bytes), 0) AS bytes FROM assets"
        ).fetchone()
        recent_failed = _job_rows_to_models(
            connection.execute(
                """
SELECT gj.id, gj.status, gj.current_stage, gj.error_code, gj.error_message, gj.prompt,
       gj.creator_id, u.email AS creator_email, g.slug AS game_slug, gj.created_at, gj.updated_at
FROM generation_jobs gj
LEFT JOIN users u ON u.id = gj.creator_id
LEFT JOIN games g ON g.id = gj.game_id
WHERE gj.status = 'failed'
ORDER BY gj.updated_at DESC
LIMIT 5
"""
            ).fetchall()
        )
    return MaintenanceOverview(
        jobCounts={row["status"]: int(row["count"]) for row in job_counts_rows},
        failedJobsLast24h=int(failed_24h),
        pendingReviews=int(pending_reviews),
        publicGames=int(public_games),
        assetsTotal=int(asset_stats["count"]),
        assetsBytes=int(asset_stats["bytes"]),
        recentFailedJobs=recent_failed,
    )


def _job_rows_to_models(rows: list[dict[str, Any]]) -> list[MaintenanceJob]:
    return [
        MaintenanceJob(
            id=str(row["id"]),
            status=row["status"],
            currentStage=row["current_stage"],
            errorCode=row["error_code"],
            errorMessage=row["error_message"],
            promptSummary=(row["prompt"] or "")[:220],
            creatorId=str(row["creator_id"]) if row["creator_id"] else None,
            creatorEmail=row["creator_email"],
            gameSlug=row["game_slug"],
            createdAt=row["created_at"],
            updatedAt=row["updated_at"],
        )
        for row in rows
    ]


def _short_text(value: str | None, limit: int = 500) -> str | None:
    if value is None:
        return None
    return value if len(value) <= limit else value[:limit] + "... [truncated]"


def _step_output_tokens(metrics: dict[str, Any]) -> int | None:
    direct = metrics.get("outputTokens")
    if isinstance(direct, int):
        return direct
    token_usage = metrics.get("tokenUsage")
    if isinstance(token_usage, dict) and isinstance(token_usage.get("outputTokens"), int):
        return token_usage["outputTokens"]
    return None


def _safe_step_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "outputTokens",
        "promptEnglishWords",
        "promptChineseChars",
        "prefixEnglishWords",
        "prefixChineseChars",
        "outputEnglishWords",
        "outputChineseChars",
        "toolName",
        "files",
        "ok",
        "error",
        "iteration",
        "strategy",
        "topology",
        "tokenUsage",
    }
    return {key: value for key, value in metrics.items() if key in allowed}


def list_failed_create_runs(limit: int = 20) -> list[MaintenanceCreateRun]:
    limit = min(max(limit, 1), 50)
    with db_connection() as connection:
        run_rows = connection.execute(
            """
SELECT
  r.id,
  r.job_id,
  r.project_id,
  p.title AS project_title,
  r.create_type,
  r.agent_mode,
  r.status,
  gj.status AS job_status,
  gj.error_code,
  gj.error_message,
  gj.prompt,
  u.email AS creator_email,
  g.slug AS game_slug,
  r.started_at,
  r.completed_at
FROM create_runs r
LEFT JOIN generation_jobs gj ON gj.id = r.job_id
LEFT JOIN agent_projects p ON p.id = r.project_id
LEFT JOIN users u ON u.id = r.user_id
LEFT JOIN games g ON g.id = r.game_id
WHERE r.status = 'failed' OR gj.status = 'failed'
ORDER BY COALESCE(r.completed_at, r.started_at) DESC
LIMIT %s
""",
            (limit,),
        ).fetchall()
        run_ids = [row["id"] for row in run_rows]
        step_rows = []
        if run_ids:
            step_rows = connection.execute(
                """
SELECT run_id, step_no, stage, status, input_summary, output_summary, metrics, created_at
FROM create_run_steps
WHERE run_id = ANY(%s::uuid[])
ORDER BY run_id, step_no ASC
""",
                (run_ids,),
            ).fetchall()

    steps_by_run: dict[str, list[MaintenanceRunStep]] = {}
    token_totals: dict[str, int] = {}
    for row in step_rows:
        metrics = row["metrics"] if isinstance(row["metrics"], dict) else {}
        output_tokens = _step_output_tokens(metrics)
        run_id = str(row["run_id"])
        if output_tokens:
            token_totals[run_id] = token_totals.get(run_id, 0) + output_tokens
        steps_by_run.setdefault(run_id, []).append(
            MaintenanceRunStep(
                stepNo=row["step_no"],
                stage=row["stage"],
                status=row["status"],
                inputSummary=_short_text(row["input_summary"]),
                outputSummary=_short_text(row["output_summary"]),
                metrics=_safe_step_metrics(metrics),
                outputTokens=output_tokens,
                createdAt=row["created_at"],
            )
        )

    return [
        MaintenanceCreateRun(
            runId=str(row["id"]),
            jobId=str(row["job_id"]) if row["job_id"] else None,
            projectId=str(row["project_id"]),
            projectTitle=row["project_title"],
            createType=row["create_type"],
            agentMode=row["agent_mode"],
            status=row["status"],
            jobStatus=row["job_status"],
            errorCode=row["error_code"],
            errorMessage=row["error_message"],
            promptSummary=(row["prompt"] or "")[:220],
            creatorEmail=row["creator_email"],
            gameSlug=row["game_slug"],
            totalOutputTokens=token_totals.get(str(row["id"]), 0),
            startedAt=row["started_at"],
            completedAt=row["completed_at"],
            steps=steps_by_run.get(str(row["id"]), []),
        )
        for row in run_rows
    ]


def list_jobs(status_filter: str | None = None, limit: int = 50) -> list[MaintenanceJob]:
    limit = min(max(limit, 1), 100)
    params: list[Any] = []
    where = ""
    if status_filter:
        where = "WHERE gj.status = %s"
        params.append(status_filter)
    params.append(limit)
    with db_connection() as connection:
        rows = connection.execute(
            f"""
SELECT gj.id, gj.status, gj.current_stage, gj.error_code, gj.error_message, gj.prompt,
       gj.creator_id, u.email AS creator_email, g.slug AS game_slug, gj.created_at, gj.updated_at
FROM generation_jobs gj
LEFT JOIN users u ON u.id = gj.creator_id
LEFT JOIN games g ON g.id = gj.game_id
{where}
ORDER BY gj.updated_at DESC
LIMIT %s
""",
            tuple(params),
        ).fetchall()
    return _job_rows_to_models(rows)


def mark_job_reviewed(job_id: str, maintainer: UserProfile, reason: str = "Reviewed by maintainer") -> MaintenanceReview:
    with db_connection() as connection:
        job = connection.execute("SELECT id FROM generation_jobs WHERE id = %s", (job_id,)).fetchone()
        if not job:
            raise HTTPException(status_code=404, detail="Job not found")
        review = connection.execute(
            """
INSERT INTO moderation_reviews (target_type, target_id, status, reason, reviewer_id, reviewed_at)
VALUES ('job', %s, 'approved', %s, %s, now())
RETURNING id, target_type, target_id, status, reason, reviewer_id, created_at, reviewed_at
""",
            (job_id, reason, maintainer.id),
        ).fetchone()
        _write_audit(connection, maintainer.id, "maintenance.job.reviewed", "job", job_id, {"reason": reason})
    return _review_from_row(review)


def retry_failed_job(job_id: str, maintainer: UserProfile, jwt_jti: str | None = None) -> tuple[CreateJob, str]:
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT id, creator_id, prompt, input_payload, status
FROM generation_jobs
WHERE id = %s
LIMIT 1
""",
            (job_id,),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        if row["status"] != "failed":
            raise HTTPException(status_code=409, detail={"code": "JOB_NOT_FAILED", "message": "Only failed jobs can be retried."})
        payload = row["input_payload"] if isinstance(row["input_payload"], dict) else {}

    creator_id = str(row["creator_id"])
    job = create_generation_job_start(
        creator_id=creator_id,
        prompt=row["prompt"],
        files=payload.get("files") if isinstance(payload.get("files"), list) else [],
        input_assets=payload.get("inputAssets") if isinstance(payload.get("inputAssets"), list) else [],
        agent_mode=payload.get("agentMode") or "chat",
        create_type=payload.get("createType") or "init",
        project_id=payload.get("projectId"),
        jwt_jti=jwt_jti,
    )
    with db_connection() as connection:
        _write_audit(
            connection,
            maintainer.id,
            "maintenance.job.retry",
            "job",
            job_id,
            {"newJobId": job.id, "creatorId": creator_id},
        )
    return job, creator_id


def _game_from_row(row: dict[str, Any]) -> MaintenanceGame:
    return MaintenanceGame(
        id=str(row["id"]),
        slug=row["slug"],
        title=row["title"],
        description=row["description"],
        visibility=row["visibility"],
        publishStatus=row["publish_status"],
        plays=int(row["plays_count"]),
        likes=int(row["likes_count"]),
        favorites=int(row["favorites_count"]),
        coverAssetId=str(row["cover_asset_id"]) if row["cover_asset_id"] else None,
        authorId=str(row["author_id"]) if row["author_id"] else None,
        updatedAt=row["updated_at"],
    )


def list_games(status_filter: str | None = None, q: str | None = None, limit: int = 50) -> list[MaintenanceGame]:
    limit = min(max(limit, 1), 100)
    clauses = ["deleted_at IS NULL"]
    params: list[Any] = []
    if status_filter:
        clauses.append("publish_status = %s")
        params.append(status_filter)
    if q:
        clauses.append("(title ILIKE %s OR slug ILIKE %s)")
        like = f"%{q}%"
        params.extend([like, like])
    params.append(limit)
    with db_connection() as connection:
        rows = connection.execute(
            f"""
SELECT id, slug, title, description, visibility, publish_status, plays_count, likes_count,
       favorites_count, cover_asset_id, author_id, updated_at
FROM games
WHERE {' AND '.join(clauses)}
ORDER BY updated_at DESC
LIMIT %s
""",
            tuple(params),
        ).fetchall()
    return [_game_from_row(row) for row in rows]


def update_game(game_id: str, request: MaintenanceGameUpdateRequest, maintainer: UserProfile) -> MaintenanceGame:
    fields: list[str] = []
    params: list[Any] = []
    changes: dict[str, Any] = {}
    for column, value in (
        ("title", request.title),
        ("description", request.description),
        ("visibility", request.visibility),
        ("publish_status", request.publishStatus),
    ):
        if value is not None:
            fields.append(f"{column} = %s")
            params.append(value)
            changes[column] = value
    if not fields:
        with db_connection() as connection:
            row = connection.execute(
                """
SELECT id, slug, title, description, visibility, publish_status, plays_count, likes_count,
       favorites_count, cover_asset_id, author_id, updated_at
FROM games
WHERE id = %s AND deleted_at IS NULL
""",
                (game_id,),
            ).fetchone()
            if not row:
                raise HTTPException(status_code=404, detail="Game not found")
            return _game_from_row(row)
    params.append(game_id)
    with db_connection() as connection:
        row = connection.execute(
            f"""
UPDATE games
SET {', '.join(fields)}, updated_at = now()
WHERE id = %s AND deleted_at IS NULL
RETURNING id, slug, title, description, visibility, publish_status, plays_count, likes_count,
          favorites_count, cover_asset_id, author_id, updated_at
""",
            tuple(params),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Game not found")
        _write_audit(connection, maintainer.id, "maintenance.game.updated", "game", game_id, changes)
    return _game_from_row(row)


def moderate_game(game_id: str, request: MaintenanceModerationRequest, maintainer: UserProfile) -> MaintenanceReview:
    if request.status not in {"approved", "rejected"}:
        raise HTTPException(status_code=400, detail="Moderation status must be approved or rejected")
    with db_connection() as connection:
        game = connection.execute("SELECT id FROM games WHERE id = %s AND deleted_at IS NULL", (game_id,)).fetchone()
        if not game:
            raise HTTPException(status_code=404, detail="Game not found")
        if request.status == "rejected":
            connection.execute(
                "UPDATE games SET publish_status = 'rejected', visibility = 'private', updated_at = now() WHERE id = %s",
                (game_id,),
            )
        review = connection.execute(
            """
INSERT INTO moderation_reviews (target_type, target_id, status, reason, reviewer_id, reviewed_at)
VALUES ('game', %s, %s, %s, %s, now())
RETURNING id, target_type, target_id, status, reason, reviewer_id, created_at, reviewed_at
""",
            (game_id, request.status, request.reason, maintainer.id),
        ).fetchone()
        _write_audit(
            connection,
            maintainer.id,
            "maintenance.game.moderated",
            "game",
            game_id,
            {"status": request.status, "reason": request.reason},
        )
    return _review_from_row(review)


def _asset_from_row(row: dict[str, Any]) -> MaintenanceAsset:
    return MaintenanceAsset(
        id=str(row["id"]),
        kind=row["kind"],
        bucket=row["bucket"],
        objectKey=row["object_key"],
        publicUrl=row["public_url"],
        contentType=row["content_type"],
        sizeBytes=int(row["size_bytes"]),
        gameId=str(row["game_id"]) if row["game_id"] else None,
        versionId=str(row["version_id"]) if row["version_id"] else None,
        jobId=str(row["job_id"]) if row["job_id"] else None,
        createdAt=row["created_at"],
    )


def list_assets(game_id: str | None = None, job_id: str | None = None, limit: int = 50) -> list[MaintenanceAsset]:
    limit = min(max(limit, 1), 100)
    clauses: list[str] = []
    params: list[Any] = []
    if game_id:
        clauses.append("game_id = %s")
        params.append(game_id)
    if job_id:
        clauses.append("job_id = %s")
        params.append(job_id)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    params.append(limit)
    with db_connection() as connection:
        rows = connection.execute(
            f"""
SELECT id, kind, bucket, object_key, public_url, content_type, size_bytes, game_id, version_id, job_id, created_at
FROM assets
{where}
ORDER BY created_at DESC
LIMIT %s
""",
            tuple(params),
        ).fetchall()
    return [_asset_from_row(row) for row in rows]


def delete_asset(asset_id: str, maintainer: UserProfile) -> dict[str, str | bool]:
    settings = get_settings()
    with db_connection() as connection:
        asset = connection.execute(
            "SELECT id, bucket, object_key FROM assets WHERE id = %s LIMIT 1",
            (asset_id,),
        ).fetchone()
        if not asset:
            raise HTTPException(status_code=404, detail="Asset not found")
        cover_ref = connection.execute("SELECT id FROM games WHERE cover_asset_id = %s LIMIT 1", (asset_id,)).fetchone()
        manifest_ref = connection.execute("SELECT id FROM game_versions WHERE manifest_asset_id = %s LIMIT 1", (asset_id,)).fetchone()
        if cover_ref or manifest_ref:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "ASSET_IN_USE",
                    "message": "Asset is referenced by a game cover or version manifest. Update metadata before deleting it.",
                },
            )
        connection.execute("DELETE FROM assets WHERE id = %s", (asset_id,))
        _write_audit(connection, maintainer.id, "maintenance.asset.deleted", "asset", asset_id, {"objectKey": asset["object_key"]})

    if asset["bucket"] != "external":
        client = Minio(
            settings.minio_endpoint,
            access_key=settings.minio_access_key,
            secret_key=settings.minio_secret_key,
            secure=False,
        )
        try:
            client.remove_object(asset["bucket"], asset["object_key"])
        except Exception:
            return {"deleted": True, "assetId": asset_id, "objectDeleted": False}
    return {"deleted": True, "assetId": asset_id, "objectDeleted": True}


def list_reviews(status_filter: str | None = None, limit: int = 50) -> list[MaintenanceReview]:
    limit = min(max(limit, 1), 100)
    params: list[Any] = []
    where = ""
    if status_filter:
        where = "WHERE status = %s"
        params.append(status_filter)
    params.append(limit)
    with db_connection() as connection:
        rows = connection.execute(
            f"""
SELECT id, target_type, target_id, status, reason, reviewer_id, created_at, reviewed_at
FROM moderation_reviews
{where}
ORDER BY created_at DESC
LIMIT %s
""",
            tuple(params),
        ).fetchall()
    return [_review_from_row(row) for row in rows]


def _review_from_row(row: dict[str, Any]) -> MaintenanceReview:
    return MaintenanceReview(
        id=str(row["id"]),
        targetType=row["target_type"],
        targetId=str(row["target_id"]),
        status=row["status"],
        reason=row["reason"],
        reviewerId=str(row["reviewer_id"]) if row["reviewer_id"] else None,
        createdAt=row["created_at"],
        reviewedAt=row["reviewed_at"],
    )


def _write_audit(
    connection: Any,
    actor_user_id: str,
    action: str,
    target_type: str,
    target_id: str | None,
    metadata: dict[str, Any],
) -> None:
    connection.execute(
        """
INSERT INTO audit_logs (actor_user_id, action, target_type, target_id, metadata)
VALUES (%s, %s, %s, %s, %s)
""",
        (actor_user_id, action, target_type, target_id, Jsonb(metadata)),
    )
