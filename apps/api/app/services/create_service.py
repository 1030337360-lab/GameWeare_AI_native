from __future__ import annotations

import hashlib
import json
import re
from io import BytesIO
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from minio import Minio
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.agents.create import run_create_pipeline
from app.agents.framework import create_agent_run_context, finalize_agent_run
from app.agents.framework.schema import ensure_agent_framework_schema
from app.agents.prompts import (
    CREATE_GAME_TEMPLATE_NAME,
    CREATE_GAME_TEMPLATE_VERSION,
    CreatePromptContext,
    build_create_game_responses_payload,
    template_metadata,
)
from app.config import get_settings
from app.database import db_connection
from app.schemas import AIConfigRequest, AIConfigState, AgentLog, CreateJob, LLMTestResult, RecentGame, UserProfile
from app.services.auth_service import redis_client
from app.services.llm_service import test_llm_config

AI_CONFIG_KEY_PREFIX = "create:ai-config:"
RECENT_GAME_KEY_PREFIX = "create:recent-game:"
_AI_CONFIG_SCHEMA_READY = False


def ensure_ai_config_schema() -> None:
    global _AI_CONFIG_SCHEMA_READY
    if _AI_CONFIG_SCHEMA_READY:
        return
    with db_connection() as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        connection.execute(
            """
CREATE TABLE IF NOT EXISTS user_ai_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  base_url text NOT NULL,
  model varchar(120) NOT NULL,
  api_key_encrypted text NOT NULL,
  provider varchar(40) NOT NULL DEFAULT 'fighting',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id)
)
"""
        )
        connection.execute(
            """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proname = 'set_updated_at' AND n.nspname = 'public'
  ) THEN
    DROP TRIGGER IF EXISTS set_user_ai_configs_updated_at ON user_ai_configs;
    CREATE TRIGGER set_user_ai_configs_updated_at
      BEFORE UPDATE ON user_ai_configs
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END $$;
"""
        )
    _AI_CONFIG_SCHEMA_READY = True


def ensure_create_runtime_schema() -> None:
    ensure_ai_config_schema()
    ensure_agent_framework_schema()


def _job_from_row(row: dict[str, Any], logs: list[dict[str, Any]]) -> CreateJob:
    input_payload = row.get("input_payload") or {}
    if not isinstance(input_payload, dict):
        input_payload = {}
    return CreateJob(
        id=str(row["id"]),
        status=row["status"],
        prompt=row["prompt"],
        createdAt=row["created_at"],
        gameId=str(row["game_id"]) if row.get("game_id") else None,
        gameSlug=row.get("game_slug"),
        playUrl=f"/play/{row['game_slug']}" if row.get("game_slug") else None,
        manifestUrl=f"/play/{row['game_slug']}/manifest" if row.get("game_slug") else None,
        agentMode=input_payload.get("agentMode"),
        createType=input_payload.get("createType"),
        projectId=input_payload.get("projectId"),
        runId=input_payload.get("runId"),
        taskId=input_payload.get("taskId"),
        resumeStatus=input_payload.get("resumeStatus"),
        logs=[
            AgentLog(
                stage=log["stage"],
                status=log["status"],
                message=log["output_summary"] or log["input_summary"] or "",
            )
            for log in logs
        ],
    )


def _ai_config_cache_key(user_id: str, jwt_jti: str | None) -> str:
    return f"{AI_CONFIG_KEY_PREFIX}{user_id}:{jwt_jti or 'session'}"


def _recent_game_cache_key(user_id: str) -> str:
    return f"{RECENT_GAME_KEY_PREFIX}{user_id}"


def _cache_ai_config(user_id: str, jwt_jti: str | None, payload: dict[str, str]) -> None:
    ttl = get_settings().jwt_ttl_seconds
    redis_client().setex(_ai_config_cache_key(user_id, jwt_jti), ttl, json.dumps(payload))


def get_ai_config_state(user: UserProfile | None, jwt_jti: str | None = None) -> AIConfigState:
    if not user:
        return AIConfigState(authenticated=False, configured=False)
    ensure_create_runtime_schema()

    cached = redis_client().get(_ai_config_cache_key(user.id, jwt_jti))
    if cached:
        try:
            payload = json.loads(cached)
            return AIConfigState(
                authenticated=True,
                configured=True,
                baseUrl=payload.get("baseUrl"),
                model=payload.get("model"),
                provider=payload.get("provider"),
            )
        except json.JSONDecodeError:
            pass

    config = _load_ai_config(user.id)
    if not config:
        return AIConfigState(authenticated=True, configured=False)
    _cache_ai_config(user.id, jwt_jti, config)
    return AIConfigState(
        authenticated=True,
        configured=True,
        baseUrl=config["baseUrl"],
        model=config["model"],
        provider=config["provider"],
    )


def upsert_ai_config(user_id: str, payload: AIConfigRequest, jwt_jti: str | None = None) -> AIConfigState:
    ensure_create_runtime_schema()
    base_url = payload.baseUrl.strip()
    model = payload.model.strip()
    provider = payload.provider.strip() or "fighting"
    api_key = payload.apiKey.strip()
    if not base_url or not model or not api_key:
        raise HTTPException(status_code=422, detail="baseUrl, model, and apiKey are required")

    with db_connection() as connection:
        connection.execute(
            """
INSERT INTO user_ai_configs (user_id, base_url, model, api_key_encrypted, provider)
VALUES (%s, %s, %s, encode(pgp_sym_encrypt(%s, %s), 'base64'), %s)
ON CONFLICT (user_id) DO UPDATE SET
  base_url = EXCLUDED.base_url,
  model = EXCLUDED.model,
  api_key_encrypted = EXCLUDED.api_key_encrypted,
  provider = EXCLUDED.provider
""",
            (user_id, base_url, model, api_key, get_settings().ai_config_encryption_secret, provider),
        )

    _cache_ai_config(
        user_id,
        jwt_jti,
        {"baseUrl": base_url, "model": model, "provider": provider, "apiKey": api_key},
    )
    return AIConfigState(authenticated=True, configured=True, baseUrl=base_url, model=model, provider=provider)


def test_ai_config_payload(payload: AIConfigRequest) -> LLMTestResult:
    return test_llm_config(
        base_url=payload.baseUrl,
        model=payload.model,
        api_key=payload.apiKey,
    )


def _load_ai_config(user_id: str, jwt_jti: str | None = None) -> dict[str, str] | None:
    ensure_create_runtime_schema()
    cached = redis_client().get(_ai_config_cache_key(user_id, jwt_jti))
    if cached:
        try:
            payload = json.loads(cached)
            if payload.get("baseUrl") and payload.get("model") and payload.get("apiKey"):
                return payload
        except json.JSONDecodeError:
            pass

    with db_connection() as connection:
        row = connection.execute(
            """
SELECT
  base_url,
  model,
  pgp_sym_decrypt(decode(api_key_encrypted, 'base64'), %s) AS api_key,
  provider
FROM user_ai_configs
WHERE user_id = %s
LIMIT 1
""",
            (get_settings().ai_config_encryption_secret, user_id),
        ).fetchone()
    if not row:
        return None
    api_key = row["api_key"]
    if not api_key:
        return None
    payload = {
        "baseUrl": row["base_url"],
        "model": row["model"],
        "provider": row["provider"],
        "apiKey": api_key,
    }
    _cache_ai_config(user_id, jwt_jti, payload)
    return payload


def _slugify(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return slug[:72] or "generated-game"


def _minio_client() -> Minio:
    settings = get_settings()
    return Minio(
        settings.minio_endpoint,
        access_key=settings.minio_access_key,
        secret_key=settings.minio_secret_key,
        secure=False,
    )


def _put_object(object_key: str, content: bytes, content_type: str) -> str:
    settings = get_settings()
    client = _minio_client()
    if not client.bucket_exists(settings.minio_bucket):
        client.make_bucket(settings.minio_bucket)
    client.put_object(
        settings.minio_bucket,
        object_key,
        BytesIO(content),
        length=len(content),
        content_type=content_type,
    )
    return f"{settings.minio_public_base_url}/{object_key}"


def _insert_agent_log(
    connection: Connection,
    job_id: str,
    stage: str,
    status_value: str,
    input_summary: str,
    output_summary: str,
    log: dict[str, Any],
) -> dict[str, Any]:
    return connection.execute(
        """
INSERT INTO agent_runs (job_id, stage, status, input_summary, output_summary, log, started_at, completed_at)
VALUES (%s, %s, %s, %s, %s, %s, now(), now())
RETURNING stage, status, input_summary, output_summary
""",
        (job_id, stage, status_value, input_summary, output_summary, Jsonb(log)),
    ).fetchone()


def _cache_recent_game(user_id: str, payload: RecentGame) -> None:
    redis_client().setex(
        _recent_game_cache_key(user_id),
        get_settings().create_recent_game_ttl_seconds,
        payload.model_dump_json(),
    )


def create_generation_job(
    creator_id: str,
    prompt: str,
    files: list[str],
    agent_mode: str = "chat",
    create_type: str = "init",
    project_id: str | None = None,
    jwt_jti: str | None = None,
) -> CreateJob:
    ensure_create_runtime_schema()
    ai_config = _load_ai_config(creator_id, jwt_jti)
    if not ai_config:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "AI_CONFIG_REQUIRED",
                "message": "AI configuration is required before creating.",
            },
        )
    if get_settings().create_validate_llm_config:
        llm_result = test_llm_config(
            base_url=ai_config["baseUrl"],
            model=ai_config["model"],
            api_key=ai_config["apiKey"],
        )
        if not llm_result.ok:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LLM_CONFIG_INVALID",
                    "message": llm_result.message,
                    "llm": llm_result.model_dump(),
                },
            )
    if not get_settings().create_static_generation:
        raise HTTPException(status_code=501, detail="Real AI generation is not implemented yet")

    cleaned_prompt = prompt.strip() or "Create a fast arcade collection game with pointer controls."
    context = create_agent_run_context(
        user_id=creator_id,
        prompt=cleaned_prompt,
        files=files,
        agent_mode=agent_mode,
        create_type=create_type,
        project_id=project_id,
        session_id=jwt_jti or "anonymous",
    )
    context.run_log.append(
        stage="ai_config_validated",
        status="succeeded",
        input_summary="AI configuration is available for this user.",
        output_summary="Create flow can continue to static generation.",
        metrics={"provider": ai_config["provider"], "model": ai_config["model"]},
    )
    context.task_store.checkpoint(
        context.task_state,
        "ai_config_validated",
        {"provider": ai_config["provider"], "model": ai_config["model"]},
        context.run_log.object_key,
    )
    prompt_context = CreatePromptContext(
        user_request=cleaned_prompt,
        create_type=context.create_type,
        agent_mode=agent_mode,
        project_id=context.project_id,
        run_id=context.run_id,
        task_id=context.task_id,
        recent_8_history=context.long_term_memory.snapshot().get("history", []),
        workspace_capability=context.workspace.capability,
        workspace_boundary=context.workspace.worktree_stub_path,
        persistent_memory_summary=context.persistent_memory.list(
            user_id=creator_id,
            project_id=context.project_id,
        ),
    )
    prompt_payload = build_create_game_responses_payload(prompt_context, ai_config["model"])
    prompt_template = template_metadata(prompt_payload)
    context.run_log.append(
        stage="prompt_rendered",
        status="succeeded",
        input_summary="Create game prompt template rendered.",
        output_summary=f"{CREATE_GAME_TEMPLATE_NAME}@{CREATE_GAME_TEMPLATE_VERSION} is ready for future LLM generation.",
        metrics={
            **prompt_template,
            "renderedCharacters": len(json.dumps(prompt_payload, ensure_ascii=False)),
        },
    )
    context.task_store.checkpoint(
        context.task_state,
        "prompt_rendered",
        {"promptTemplate": prompt_template, "responsesPayload": prompt_payload},
        context.run_log.object_key,
    )
    game_id = str(uuid4())
    version_id = str(uuid4())
    context.run_log.append(
        stage="static_generation_started",
        status="running",
        input_summary="Static generation pipeline is starting.",
        output_summary="Game and version identifiers allocated.",
        metrics={"gameId": game_id, "versionId": version_id},
    )
    draft_pipeline = run_create_pipeline(
        prompt=cleaned_prompt,
        agent_mode=agent_mode,
        game_slug="pending",
        game_id=game_id,
        version_id=version_id,
        ai_config=ai_config,
        prompt_template=prompt_template,
    )
    game_slug = f"{_slugify(draft_pipeline.title)}-{game_id[:8]}"
    pipeline = run_create_pipeline(
        prompt=cleaned_prompt,
        agent_mode=agent_mode,
        game_slug=game_slug,
        game_id=game_id,
        version_id=version_id,
        ai_config=ai_config,
        prompt_template=prompt_template,
    )
    agent_mode = pipeline.source["agentMode"]
    context.agent_mode = agent_mode
    context.short_term_memory.record_tool_call(
        {"tool": "run_create_pipeline", "status": "succeeded", "agentMode": agent_mode}
    )
    context.run_log.append(
        stage="static_generation_completed",
        status="succeeded",
        input_summary="Static pipeline returned generated artifacts.",
        output_summary=f"{len(pipeline.artifacts)} artifacts are ready for object storage.",
        metrics={"artifactCount": len(pipeline.artifacts), "runtime": pipeline.runtime},
    )
    context.task_store.checkpoint(
        context.task_state,
        "static_generation_completed",
        {"artifactCount": len(pipeline.artifacts), "runtime": pipeline.runtime},
        context.run_log.object_key,
    )
    storage_prefix = f"games/{game_id}/versions/1"
    api_base = f"http://localhost:{get_settings().api_port}"
    document_url = f"{api_base}/play/{game_slug}/document"

    manifest = {
        "id": game_slug,
        "gameId": game_id,
        "versionId": version_id,
        "version": "1",
        "runtime": pipeline.runtime,
        "entry": pipeline.entry_file,
        "documentUrl": document_url,
        "bundleUrl": document_url,
        "sandbox": ["allow-scripts"],
        "input": ["pointer", "mouse", "keyboard", "touch"],
        "communication": "postMessage",
        "agentMode": agent_mode,
        "assets": [],
        "limits": {"maxInitialBytes": 10485760, "maxTotalBytes": 20971520},
    }

    manifest_key = f"{storage_prefix}/manifest.json"
    manifest_bytes = json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8")
    manifest_public_url = _put_object(manifest_key, manifest_bytes, "application/json")
    uploaded_artifacts = []
    for artifact in pipeline.artifacts:
        object_key = f"{storage_prefix}/{artifact.filename}"
        stored_url = _put_object(object_key, artifact.content, artifact.content_type)
        public_url = document_url if artifact.filename == pipeline.entry_file else stored_url
        uploaded_artifacts.append((artifact, object_key, public_url))
    context.short_term_memory.record_file_edit(
        {"operation": "upload_artifacts", "storagePrefix": storage_prefix, "artifactCount": len(uploaded_artifacts) + 1}
    )
    context.run_log.append(
        stage="objects_uploaded",
        status="succeeded",
        input_summary="Generated objects uploaded to MinIO.",
        output_summary="Manifest and playable artifacts have object keys.",
        metrics={
            "storagePrefix": storage_prefix,
            "manifestObjectKey": manifest_key,
            "artifactCount": len(uploaded_artifacts),
        },
    )

    with db_connection() as connection:
        job = connection.execute(
            """
INSERT INTO generation_jobs (creator_id, prompt, input_payload, status, current_stage, started_at)
VALUES (%s, %s, %s, 'planning', 'planner', now())
RETURNING id, status, prompt, input_payload, created_at, game_id
""",
            (
                creator_id,
                cleaned_prompt,
                Jsonb(
                    {
                        "files": files,
                        "agentMode": agent_mode,
                        "createType": context.create_type,
                        "projectId": context.project_id,
                        "runId": context.run_id,
                        "taskId": context.task_id,
                        "resumeStatus": context.task_state.resume_status,
                        "promptTemplate": prompt_template,
                        "aiConfig": {"model": ai_config["model"], "provider": ai_config["provider"]},
                    }
                ),
            ),
        ).fetchone()
        job_id = str(job["id"])

        logs = [
            _insert_agent_log(
                connection,
                job_id,
                run.stage,
                run.status,
                run.input_summary,
                run.output_summary,
                run.log,
            )
            for run in pipeline.runs
        ]

        game = connection.execute(
            """
INSERT INTO games (
  id,
  slug,
  author_id,
  title,
  description,
  visibility,
  publish_status,
  metadata,
  published_at
)
VALUES (%s, %s, %s, %s, %s, 'public', 'published', %s, now())
RETURNING id, slug, title
""",
            (
                game_id,
                game_slug,
                creator_id,
                pipeline.title,
                pipeline.description,
                Jsonb({"section": "Recently Created", "createdBy": "static-create", "agentMode": agent_mode}),
            ),
        ).fetchone()

        version = connection.execute(
            """
INSERT INTO game_versions (
  id,
  game_id,
  version_no,
  source_job_id,
  runtime,
  entry_file,
  build_status,
  safety_status,
  storage_prefix,
  metadata
)
VALUES (%s, %s, 1, %s, %s, %s, 'succeeded', 'passed', %s, %s)
RETURNING id
""",
            (
                version_id,
                game_id,
                job_id,
                pipeline.runtime,
                pipeline.entry_file,
                storage_prefix,
                Jsonb({"stubbed": True, "agentMode": agent_mode}),
            ),
        ).fetchone()

        manifest_asset = connection.execute(
            """
INSERT INTO assets (
  owner_id, game_id, version_id, job_id, kind, bucket, object_key, public_url, content_type, size_bytes, sha256
)
VALUES (%s, %s, %s, %s, 'manifest', %s, %s, %s, 'application/json', %s, %s)
RETURNING id
""",
            (
                creator_id,
                game_id,
                version_id,
                job_id,
                get_settings().minio_bucket,
                manifest_key,
                manifest_public_url,
                len(manifest_bytes),
                hashlib.sha256(manifest_bytes).hexdigest(),
            ),
        ).fetchone()

        artifact_asset_ids: list[tuple[str, str]] = []
        cover_asset_id = None
        bundle_public_url = document_url
        for artifact, object_key, public_url in uploaded_artifacts:
            asset = connection.execute(
                """
INSERT INTO assets (
  owner_id, game_id, version_id, job_id, kind, bucket, object_key, public_url, content_type, size_bytes, sha256, width, height
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id
""",
                (
                    creator_id,
                    game_id,
                    version_id,
                    job_id,
                    artifact.kind,
                    get_settings().minio_bucket,
                    object_key,
                    public_url,
                    artifact.content_type.split(";", 1)[0],
                    len(artifact.content),
                    hashlib.sha256(artifact.content).hexdigest(),
                    1200 if artifact.kind == "cover" else None,
                    900 if artifact.kind == "cover" else None,
                ),
            ).fetchone()
            artifact_asset_ids.append((asset["id"], artifact.purpose))
            if artifact.kind == "cover":
                cover_asset_id = asset["id"]
            if artifact.kind == "bundle":
                bundle_public_url = public_url

        connection.execute(
            "UPDATE game_versions SET manifest_asset_id = %s WHERE id = %s",
            (manifest_asset["id"], version["id"]),
        )
        connection.execute(
            "UPDATE games SET current_version_id = %s, cover_asset_id = %s WHERE id = %s",
            (version["id"], cover_asset_id, game_id),
        )
        connection.execute(
            """
UPDATE generation_jobs
SET game_id = %s, version_id = %s, status = 'completed', current_stage = 'publisher', completed_at = now()
WHERE id = %s
""",
            (game_id, version_id, job_id),
        )
        for asset_id, purpose in [(manifest_asset["id"], "manifest"), *artifact_asset_ids]:
            connection.execute(
                """
INSERT INTO job_artifacts (job_id, asset_id, purpose)
VALUES (%s, %s, %s)
ON CONFLICT DO NOTHING
""",
                (job_id, asset_id, purpose),
            )
        logs.append(
            _insert_agent_log(
                connection,
                job_id,
                "publisher",
                "succeeded",
                "Uploaded generated game files to MinIO and persisted SQL metadata.",
                "Game is published and ready for iframe play.",
                {
                    "stubbed": True,
                    "agentMode": agent_mode,
                    "bundleUrl": bundle_public_url,
                    "manifestUrl": manifest_public_url,
                },
            )
        )
        completed = connection.execute(
            """
SELECT gj.id, gj.status, gj.prompt, gj.input_payload, gj.created_at, gj.game_id, g.slug AS game_slug
FROM generation_jobs gj
LEFT JOIN games g ON g.id = gj.game_id
WHERE gj.id = %s
LIMIT 1
""",
            (job_id,),
        ).fetchone()

    context.run_log.append(
        stage="sql_persisted",
        status="succeeded",
        input_summary="Generated game metadata persisted to PostgreSQL.",
        output_summary="Job, game, version, assets, artifacts, and legacy agent logs are linked.",
        metrics={"jobId": job_id, "gameSlug": game_slug, "assetCount": len(artifact_asset_ids) + 1},
    )
    recent = RecentGame(
        gameId=game_id,
        gameSlug=game_slug,
        title=game["title"],
        playUrl=f"/play/{game_slug}",
        jobId=job_id,
    )
    _cache_recent_game(creator_id, recent)
    summary = {
        "title": game["title"],
        "gameSlug": game_slug,
        "playUrl": f"/play/{game_slug}",
        "manifestUrl": f"/play/{game_slug}/manifest",
        "storagePrefix": storage_prefix,
        "implementationPath": [record["stage"] for record in context.run_log.records],
        "effectSummary": {
            "runtime": pipeline.runtime,
            "entryFile": pipeline.entry_file,
            "artifactCount": len(uploaded_artifacts) + 1,
            "stubbed": True,
        },
        "promptTemplate": prompt_template,
    }
    context.persistent_memory.put(
        user_id=creator_id,
        project_id=context.project_id,
        memory_type="project_tag",
        tags=["published", agent_mode],
        summary="Generated game was published.",
        payload=summary,
    )
    context.long_term_memory.append_history("assistant", f"Created playable game {game['title']} at /play/{game_slug}.")
    context.short_term_memory.record_test({"name": "static_generation_smoke", "status": "succeeded"})
    context.run_log.append(
        stage="run_completed",
        status="succeeded",
        input_summary="Create run completed.",
        output_summary="Playable game is published and run log is finalized.",
        metrics=summary,
    )
    finalize_agent_run(
        context=context,
        status_value="completed",
        job_id=job_id,
        game_id=game_id,
        version_id=version_id,
        summary=summary,
        final_answer=f"Game {game['title']} is ready to play.",
    )
    return _job_from_row(completed, logs)

def get_generation_job(job_id: str) -> CreateJob | None:
    with db_connection() as connection:
        job = connection.execute(
            """
SELECT gj.id, gj.status, gj.prompt, gj.input_payload, gj.created_at, gj.game_id, g.slug AS game_slug
FROM generation_jobs gj
LEFT JOIN games g ON g.id = gj.game_id
WHERE gj.id = %s
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


def get_recent_game(user_id: str) -> RecentGame | None:
    cached = redis_client().get(_recent_game_cache_key(user_id))
    if cached:
        try:
            return RecentGame.model_validate_json(cached)
        except ValueError:
            pass

    with db_connection() as connection:
        row = connection.execute(
            """
SELECT
  gj.id AS job_id,
  g.id AS game_id,
  g.slug,
  g.title
FROM generation_jobs gj
JOIN games g ON g.id = gj.game_id
WHERE
  gj.creator_id = %s
  AND gj.status = 'completed'
  AND g.deleted_at IS NULL
ORDER BY gj.completed_at DESC NULLS LAST, gj.created_at DESC
LIMIT 1
""",
            (user_id,),
        ).fetchone()
    if not row:
        return None
    recent = RecentGame(
        gameId=str(row["game_id"]),
        gameSlug=row["slug"],
        title=row["title"],
        playUrl=f"/play/{row['slug']}",
        jobId=str(row["job_id"]),
    )
    _cache_recent_game(user_id, recent)
    return recent

