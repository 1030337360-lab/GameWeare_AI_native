from __future__ import annotations

import hashlib
import json
import re
import base64
from io import BytesIO
from typing import Any
from uuid import uuid4

from fastapi import HTTPException, status
from minio import Minio
from psycopg import Connection
from psycopg.types.json import Jsonb

from app.agents.create import (
    COVER_AGENT_NAME,
    COVER_AGENT_VERSION,
    COVER_HEIGHT,
    COVER_WIDTH,
    AgentArtifact,
    CoverAgentArtifact,
    build_cover_responses_payload,
    build_pipeline_from_main_agent_output,
    parse_cover_agent_output,
    parse_main_agent_json_output,
    run_create_pipeline,
)
from app.agents.framework import create_agent_run_context, finalize_agent_run, load_agent_run_context_for_job
from app.agents.framework.schema import ensure_agent_framework_schema
from app.agents.graphs.llm_adapter import OpenAIResponsesGraphAdapter
from app.agents.graphs.recording import LLMCallRecorder
from app.agents.prompts import (
    CREATE_GAME_TEMPLATE_NAME,
    CREATE_GAME_TEMPLATE_VERSION,
    template_metadata,
)
from app.agents.strategies import AgentRequestSettings, select_agent_strategy
from app.agents.tools import build_builtin_tool_registry, list_builtin_tool_metadata
from app.config import get_settings
from app.database import db_connection
from app.schemas import AIConfigRequest, AIConfigState, AgentLog, CreateInputAsset, CreateJob, LLMTestResult, RecentGame, UserProfile
from app.services.auth_service import redis_client
from app.services.llm_service import test_llm_config

AI_CONFIG_KEY_PREFIX = "create:ai-config:"
RECENT_GAME_KEY_PREFIX = "create:recent-game:"
_AI_CONFIG_SCHEMA_READY = False


class MultimodalUnsupportedError(RuntimeError):
    pass


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
        return AIConfigState(authenticated=False, configured=False, staticGeneration=get_settings().create_static_generation)
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
                staticGeneration=get_settings().create_static_generation,
            )
        except json.JSONDecodeError:
            pass

    config = _load_ai_config(user.id)
    if not config:
        return AIConfigState(authenticated=True, configured=False, staticGeneration=get_settings().create_static_generation)
    _cache_ai_config(user.id, jwt_jti, config)
    return AIConfigState(
        authenticated=True,
        configured=True,
        baseUrl=config["baseUrl"],
        model=config["model"],
        provider=config["provider"],
        staticGeneration=get_settings().create_static_generation,
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
    return AIConfigState(authenticated=True, configured=True, baseUrl=base_url, model=model, provider=provider, staticGeneration=get_settings().create_static_generation)


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


def _make_graph_adapter(ai_config: dict[str, str]) -> OpenAIResponsesGraphAdapter:
    return OpenAIResponsesGraphAdapter(
        base_url=ai_config["baseUrl"],
        api_key=ai_config["apiKey"],
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


def _input_asset_dicts(input_assets: list[CreateInputAsset | dict[str, Any]] | None) -> list[dict[str, Any]]:
    normalized: list[dict[str, Any]] = []
    for asset in input_assets or []:
        if isinstance(asset, CreateInputAsset):
            normalized.append(asset.model_dump())
        elif isinstance(asset, dict):
            normalized.append(dict(asset))
    return normalized


def _load_create_input_assets(user_id: str, input_assets: list[CreateInputAsset | dict[str, Any]] | None) -> list[dict[str, Any]]:
    requested = _input_asset_dicts(input_assets)
    if not requested:
        return []
    asset_ids = [asset.get("assetId") for asset in requested if isinstance(asset.get("assetId"), str)]
    if len(asset_ids) != len(requested):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={"code": "INVALID_INPUT_ASSETS", "message": "Every input asset must include assetId."},
        )
    with db_connection() as connection:
        rows = connection.execute(
            """
SELECT id, object_key, public_url, content_type, size_bytes
FROM assets
WHERE owner_id = %s AND kind = 'upload' AND id = ANY(%s::uuid[])
""",
            (user_id, asset_ids),
        ).fetchall()
    rows_by_id = {str(row["id"]): row for row in rows}
    if len(rows_by_id) != len(set(asset_ids)):
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "INPUT_ASSET_NOT_FOUND", "message": "One or more uploaded input assets were not found."},
        )
    resolved: list[dict[str, Any]] = []
    for asset in requested:
        row = rows_by_id[str(asset["assetId"])]
        content_type = row["content_type"]
        if content_type not in {"image/png", "image/jpeg", "image/webp", "image/gif"}:
            raise HTTPException(
                status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
                detail={"code": "UNSUPPORTED_INPUT_ASSET", "message": "Create input assets must be images."},
            )
        resolved.append(
            {
                "assetId": str(row["id"]),
                "objectKey": row["object_key"],
                "publicUrl": row["public_url"],
                "contentType": content_type,
                "filename": asset.get("filename"),
                "size": int(row["size_bytes"] or 0),
            }
        )
    return resolved


def _asset_to_data_url(asset: dict[str, Any]) -> dict[str, Any]:
    settings = get_settings()
    client = _minio_client()
    response = client.get_object(settings.minio_bucket, asset["objectKey"])
    try:
        content = response.read()
    finally:
        response.close()
        response.release_conn()
    content_type = str(asset.get("contentType") or "application/octet-stream")
    return {
        **asset,
        "dataUrl": f"data:{content_type};base64,{base64.b64encode(content).decode('ascii')}",
    }


def _assets_for_prompt(input_assets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_asset_to_data_url(asset) for asset in input_assets]


def _is_multimodal_unsupported_error(raw: Any) -> bool:
    text = json.dumps(raw, ensure_ascii=False, default=str).lower()
    markers = [
        "input_image",
        "image_url",
        "vision",
        "multimodal",
        "modalities",
        "unsupported image",
        "does not support image",
        "image input",
    ]
    return any(marker in text for marker in markers)


def _redacted_prompt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    safe_payload = json.loads(json.dumps(payload, ensure_ascii=False, default=str))
    for item in safe_payload.get("input", []):
        if not isinstance(item, dict):
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        for content_item in content:
            if isinstance(content_item, dict) and content_item.get("type") == "input_image":
                content_item["image_url"] = "[image omitted]"
    return safe_payload


def _cleanup_failed_input_assets(*, job_id: str, user_id: str, input_assets: list[dict[str, Any]]) -> None:
    if not input_assets:
        return
    settings = get_settings()
    client = _minio_client()
    asset_ids = [asset["assetId"] for asset in input_assets if asset.get("assetId")]
    for asset in input_assets:
        object_key = asset.get("objectKey")
        if isinstance(object_key, str) and object_key:
            try:
                client.remove_object(settings.minio_bucket, object_key)
            except Exception:
                pass
    with db_connection() as connection:
        connection.execute(
            """
DELETE FROM assets
WHERE owner_id = %s AND kind = 'upload' AND id = ANY(%s::uuid[])
""",
            (user_id, asset_ids),
        )
        connection.execute(
            """
UPDATE generation_jobs
SET input_payload = jsonb_set(COALESCE(input_payload, '{}'::jsonb), '{inputAssets}', '[]'::jsonb, true)
WHERE id = %s
""",
            (job_id,),
        )
    try:
        redis_client().delete(f"create:input-assets:{job_id}")
    except Exception:
        pass


def _input_assets_for_job(job_id: str) -> list[dict[str, Any]]:
    with db_connection() as connection:
        row = connection.execute("SELECT input_payload FROM generation_jobs WHERE id = %s", (job_id,)).fetchone()
    if not row or not isinstance(row["input_payload"], dict):
        return []
    input_assets = row["input_payload"].get("inputAssets")
    return input_assets if isinstance(input_assets, list) else []


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


def _main_agent_output_value(graph_result: Any) -> str | dict[str, Any]:
    def unwrap(value: str | dict[str, Any]) -> str | dict[str, Any]:
        parsed = value
        if isinstance(value, str):
            try:
                loaded = json.loads(value)
                parsed = loaded if isinstance(loaded, dict) else value
            except json.JSONDecodeError:
                return value
        if isinstance(parsed, dict) and parsed.get("type") == "final" and isinstance(parsed.get("output"), dict):
            return parsed["output"]
        return parsed

    final_output = graph_result.final_output
    if isinstance(final_output, dict):
        text = final_output.get("text")
        if isinstance(text, str) and text.strip():
            return unwrap(text)
        output = final_output.get("output")
        if isinstance(output, dict):
            return unwrap(output)
        return unwrap(final_output)
    last_message = graph_result.messages[-1] if graph_result.messages else {}
    text = last_message.get("text") if isinstance(last_message, dict) else None
    return unwrap(text) if isinstance(text, str) else ""


def _cover_prompt_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    rendered = json.dumps(payload, ensure_ascii=False, default=str)
    return {
        "agent": COVER_AGENT_NAME,
        "version": COVER_AGENT_VERSION,
        "targetWidth": COVER_WIDTH,
        "targetHeight": COVER_HEIGHT,
        "renderedCharacters": len(rendered),
        "injectedFields": [
            "createRequest",
            "gameTitle",
            "gameDescription",
            "implementationSummary",
            "styleTags",
            "coverSpec",
        ],
    }


def _safe_cover_llm_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    token_usage = metrics.get("tokenUsage") if isinstance(metrics.get("tokenUsage"), dict) else {}
    return {
        "agent": COVER_AGENT_NAME,
        "version": COVER_AGENT_VERSION,
        "promptEnglishWords": metrics.get("promptEnglishWords"),
        "promptChineseChars": metrics.get("promptChineseChars"),
        "prefixEnglishWords": metrics.get("prefixEnglishWords"),
        "prefixChineseChars": metrics.get("prefixChineseChars"),
        "outputEnglishWords": metrics.get("outputEnglishWords"),
        "outputChineseChars": metrics.get("outputChineseChars"),
        "outputTokens": token_usage.get("outputTokens"),
        "tokenUsage": token_usage,
    }


def _cover_extension_for_content_type(content_type: str) -> str:
    normalized = content_type.split(";", 1)[0].strip().lower()
    return {
        "image/png": "png",
        "image/webp": "webp",
        "image/jpeg": "jpg",
        "image/svg+xml": "svg",
    }.get(normalized, "png")


def _cover_filename(artifact: AgentArtifact) -> str:
    return f"cover.{_cover_extension_for_content_type(artifact.content_type)}"


def _source_with_cover_metadata(
    *,
    artifact: AgentArtifact,
    filenames: list[str],
    cover_artifact: CoverAgentArtifact | None,
    use_static_generation: bool,
) -> AgentArtifact:
    try:
        source_document = json.loads(artifact.content.decode("utf-8"))
        if not isinstance(source_document, dict):
            source_document = {}
    except (UnicodeDecodeError, json.JSONDecodeError):
        source_document = {"rawSource": artifact.content.decode("utf-8", errors="replace")[:4000]}
    source_document["files"] = ["manifest.json", *filenames]
    if cover_artifact:
        source_document["coverAgent"] = {
            "agent": COVER_AGENT_NAME,
            "version": COVER_AGENT_VERSION,
            "required": True,
            "contentType": cover_artifact.content_type,
            "width": cover_artifact.width,
            "height": cover_artifact.height,
            "sizeBytes": cover_artifact.size_bytes,
            "rawKind": cover_artifact.raw_kind,
        }
    else:
        source_document["coverAgent"] = {
            "agent": "static-test-cover",
            "required": False,
            "staticGeneration": use_static_generation,
        }
    return AgentArtifact(
        artifact.filename,
        json.dumps(source_document, ensure_ascii=False, indent=2).encode("utf-8"),
        artifact.content_type,
        artifact.kind,
        artifact.purpose,
    )


def _publish_artifacts(
    *,
    pipeline: Any,
    cover_artifact: CoverAgentArtifact | None,
    use_static_generation: bool,
) -> list[AgentArtifact]:
    artifacts: list[AgentArtifact] = []
    for artifact in pipeline.artifacts:
        if cover_artifact and artifact.kind == "cover":
            continue
        artifacts.append(artifact)
    if cover_artifact:
        artifacts.append(
            AgentArtifact(
                _cover_filename(cover_artifact.artifact),
                cover_artifact.artifact.content,
                cover_artifact.artifact.content_type,
                "cover",
                "preview",
            )
        )
    if not use_static_generation and not any(artifact.kind == "cover" for artifact in artifacts):
        raise RuntimeError("Cover Agent did not produce the required cover asset.")

    filenames = [artifact.filename for artifact in artifacts]
    return [
        _source_with_cover_metadata(
            artifact=artifact,
            filenames=filenames,
            cover_artifact=cover_artifact,
            use_static_generation=use_static_generation,
        )
        if artifact.kind == "source" or artifact.filename == "source.json"
        else artifact
        for artifact in artifacts
    ]


def _generate_required_cover_artifact(
    *,
    ai_config: dict[str, str],
    context: Any,
    cleaned_prompt: str,
    pipeline: Any,
    parsed_output: dict[str, Any],
) -> CoverAgentArtifact:
    cover = parsed_output.get("cover") if isinstance(parsed_output.get("cover"), dict) else {}
    tags = cover.get("tags") if isinstance(cover.get("tags"), list) else []
    prompt_payload = build_cover_responses_payload(
        model=ai_config["model"],
        user_request=cleaned_prompt,
        game_title=pipeline.title,
        game_description=pipeline.description,
        implementation_summary=str(parsed_output.get("implementationSummary") or ""),
        style_tags=[str(tag) for tag in tags if isinstance(tag, str)],
    )
    prompt_metadata = _cover_prompt_metadata(prompt_payload)
    context.run_log.append(
        stage="cover_prompt_rendered",
        status="succeeded",
        input_summary="Cover Agent prompt rendered.",
        output_summary=f"{COVER_AGENT_NAME}@{COVER_AGENT_VERSION} is ready.",
        metrics=prompt_metadata,
    )
    context.task_store.checkpoint(
        context.task_state,
        "cover_prompt_rendered",
        {"coverPrompt": prompt_metadata},
        context.run_log.object_key,
    )
    context.run_log.append(
        stage="cover_generation_started",
        status="running",
        input_summary="Cover Agent is calling the configured LLM provider.",
        output_summary="Waiting for one durable catalog cover image.",
        metrics={
            "agent": COVER_AGENT_NAME,
            "model": ai_config["model"],
            "targetWidth": COVER_WIDTH,
            "targetHeight": COVER_HEIGHT,
        },
    )
    result = _make_graph_adapter(ai_config).invoke(prompt_payload)
    context.short_term_memory.record_llm_call(
        {
            "kind": "cover_llm_call",
            "agent": COVER_AGENT_NAME,
            "metrics": _safe_cover_llm_metrics(result.metrics),
            "recordedAt": None,
        }
    )
    context.long_term_memory.append_history(
        "llm",
        "Cover Agent returned a cover candidate.",
        metadata={"kind": "cover_llm_call", "metrics": _safe_cover_llm_metrics(result.metrics)},
    )
    context.run_log.append(
        stage="cover_llm_call",
        status="failed" if isinstance(result.raw, dict) and result.raw.get("ok") is False else "succeeded",
        input_summary=str(result.metrics.get("promptPrefix") or "")[:500],
        output_summary="Cover model response received." if result.text or result.raw else "Cover model returned an empty response.",
        metrics=_safe_cover_llm_metrics(result.metrics),
    )
    if isinstance(result.raw, dict) and result.raw.get("ok") is False:
        raise RuntimeError("Cover Agent provider call failed.")
    cover_artifact = parse_cover_agent_output(result)
    context.run_log.append(
        stage="cover_generated",
        status="succeeded",
        input_summary="Cover Agent output parsed.",
        output_summary=cover_artifact.summary,
        metrics={
            "agent": COVER_AGENT_NAME,
            "contentType": cover_artifact.content_type,
            "sizeBytes": cover_artifact.size_bytes,
            "width": cover_artifact.width,
            "height": cover_artifact.height,
            "rawKind": cover_artifact.raw_kind,
        },
    )
    return cover_artifact


def _cache_recent_game(user_id: str, payload: RecentGame) -> None:
    redis_client().setex(
        _recent_game_cache_key(user_id),
        get_settings().create_recent_game_ttl_seconds,
        payload.model_dump_json(),
    )


def _fail_generation_job(
    *,
    context: Any | None,
    job_id: str,
    code: str,
    message: str,
    stage: str,
    metrics: dict[str, Any] | None = None,
) -> None:
    if context:
        context.run_log.append(
            stage=stage,
            status="failed",
            input_summary="Create generation failed.",
            output_summary=message[:500],
            metrics={"code": code, **(metrics or {})},
        )
        context.run_log.append(
            stage="job_failed",
            status="failed",
            input_summary="Create job failed.",
            output_summary=message[:500],
            metrics={"code": code, "stage": stage},
        )
        finalize_agent_run(
            context=context,
            status_value="failed",
            job_id=job_id,
            summary={"code": code, "message": message, "stage": stage},
            final_answer=message,
        )
    with db_connection() as connection:
        connection.execute(
            """
UPDATE generation_jobs
SET status = 'failed', current_stage = %s, error_code = %s, error_message = %s, completed_at = now()
WHERE id = %s
""",
            (stage, code, message[:1000], job_id),
        )


def _insert_pending_generation_job(
    *,
    creator_id: str,
    prompt: str,
    files: list[str],
    input_assets: list[dict[str, Any]],
    agent_mode: str,
    context: Any,
    ai_config: dict[str, str],
) -> CreateJob:
    with db_connection() as connection:
        row = connection.execute(
            """
INSERT INTO generation_jobs (creator_id, prompt, input_payload, status, current_stage, started_at)
VALUES (%s, %s, %s, 'planning', 'run_created', now())
RETURNING id, status, prompt, input_payload, created_at, game_id
""",
            (
                creator_id,
                prompt,
                Jsonb(
                    {
                        "files": files,
                        "inputAssets": input_assets,
                        "agentMode": agent_mode,
                        "createType": context.create_type,
                        "projectId": context.project_id,
                        "runId": context.run_id,
                        "taskId": context.task_id,
                        "resumeStatus": context.task_state.resume_status,
                        "aiConfig": {"model": ai_config["model"], "provider": ai_config["provider"]},
                    }
                ),
            ),
        ).fetchone()
        connection.execute("UPDATE create_runs SET job_id = %s WHERE id = %s", (row["id"], context.run_id))
    context.run_log.append(
        stage="job_created",
        status="succeeded",
        input_summary="Create job row created for background generation.",
        output_summary="The browser can now subscribe to run events.",
        metrics={"jobId": str(row["id"]), "staticGeneration": get_settings().create_static_generation},
    )
    return _job_from_row(row, [])


def create_generation_job_start(
    creator_id: str,
    prompt: str,
    files: list[str],
    input_assets: list[CreateInputAsset | dict[str, Any]] | None = None,
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
    resolved_input_assets = _load_create_input_assets(creator_id, input_assets)
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
        output_summary=(
            "Static test generation is explicitly enabled."
            if get_settings().create_static_generation
            else "Real LLM generation will run in the background."
        ),
        metrics={
            "provider": ai_config["provider"],
            "model": ai_config["model"],
            "staticGeneration": get_settings().create_static_generation,
            "inputAssetCount": len(resolved_input_assets),
        },
    )
    context.task_store.checkpoint(
        context.task_state,
        "ai_config_validated",
        {"provider": ai_config["provider"], "model": ai_config["model"]},
        context.run_log.object_key,
    )
    return _insert_pending_generation_job(
        creator_id=creator_id,
        prompt=cleaned_prompt,
        files=files,
        input_assets=resolved_input_assets,
        agent_mode=agent_mode,
        context=context,
        ai_config=ai_config,
    )


def _update_job_stage(job_id: str, status_value: str, stage: str) -> None:
    with db_connection() as connection:
        connection.execute(
            "UPDATE generation_jobs SET status = %s, current_stage = %s WHERE id = %s",
            (status_value, stage, job_id),
        )


def execute_generation_job(job_id: str, creator_id: str, jwt_jti: str | None = None) -> None:
    context = None
    try:
        ensure_create_runtime_schema()
        ai_config = _load_ai_config(creator_id, jwt_jti)
        if not ai_config:
            raise RuntimeError("AI configuration is no longer available for this job.")
        context, cleaned_prompt, files, input_assets = load_agent_run_context_for_job(
            user_id=creator_id,
            job_id=job_id,
            session_id=jwt_jti or "anonymous",
        )
        _execute_generation_job_loaded(
            job_id=job_id,
            creator_id=creator_id,
            cleaned_prompt=cleaned_prompt,
            files=files,
            input_assets=input_assets,
            ai_config=ai_config,
            context=context,
        )
    except Exception as exc:
        input_assets = _input_assets_for_job(job_id)
        if input_assets:
            _cleanup_failed_input_assets(job_id=job_id, user_id=creator_id, input_assets=input_assets)
        _fail_generation_job(
            context=context,
            job_id=job_id,
            code="MULTIMODAL_UNSUPPORTED" if isinstance(exc, MultimodalUnsupportedError) else exc.__class__.__name__,
            message=str(exc) or "Create generation failed.",
            stage="run_failed",
        )


def _execute_generation_job_loaded(
    *,
    job_id: str,
    creator_id: str,
    cleaned_prompt: str,
    files: list[str],
    input_assets: list[dict[str, Any]],
    ai_config: dict[str, str],
    context: Any,
) -> None:
    _update_job_stage(job_id, "planning", "prompt_render")
    tool_metadata = list_builtin_tool_metadata()
    prompt_settings = AgentRequestSettings.from_create_context(
        user_request=cleaned_prompt,
        create_type=context.create_type,
        agent_mode=context.agent_mode,
        recent_8_history=context.long_term_memory.snapshot().get("history", []),
        workspace_capability=context.workspace.capability,
        workspace_boundary=context.workspace.worktree_stub_path,
        persistent_memory_summary=context.persistent_memory.list(
            user_id=creator_id,
            project_id=context.project_id,
        ),
        tool_metadata=tool_metadata,
        input_assets=_assets_for_prompt(input_assets),
    )
    prompt_tool_result = build_builtin_tool_registry().call(
        "llm.prompt_render",
        {
            "userRequest": prompt_settings.user_request,
            "createType": prompt_settings.create_type,
            "agentMode": prompt_settings.agent_mode,
            "recent8History": prompt_settings.recent_8_history,
            "workspaceCapability": prompt_settings.workspace_capability,
            "workspaceBoundary": prompt_settings.workspace_boundary,
            "persistentMemorySummary": prompt_settings.persistent_memory_summary,
            "toolMetadata": tool_metadata,
            "inputAssets": prompt_settings.input_assets,
            "model": ai_config["model"],
        },
    )
    context.short_term_memory.record_tool_call(
        {"tool": "llm.prompt_render", "status": "succeeded" if prompt_tool_result["ok"] else "failed", "dryRun": True}
    )
    if not prompt_tool_result["ok"] or "payload" not in prompt_tool_result.get("data", {}):
        raise RuntimeError("Create prompt rendering failed.")

    prompt_payload = prompt_tool_result["data"]["payload"]
    safe_prompt_payload = _redacted_prompt_payload(prompt_payload)
    prompt_template = template_metadata(prompt_payload)
    strategy = select_agent_strategy(prompt_settings)
    strategy_metadata = strategy.plan(prompt_settings).to_metadata()
    context.run_log.append(
        stage="agent_strategy_selected",
        status="succeeded",
        input_summary="Backend selected the agent strategy from createType and agentMode.",
        output_summary=f"{strategy_metadata['strategy']} strategy framework selected.",
        metrics=strategy_metadata,
    )
    context.run_log.append(
        stage="prompt_rendered",
        status="succeeded",
        input_summary="Create game prompt template rendered.",
        output_summary=f"{CREATE_GAME_TEMPLATE_NAME}@{CREATE_GAME_TEMPLATE_VERSION} is ready.",
        metrics={**prompt_template, "strategy": strategy_metadata, "renderedCharacters": len(json.dumps(safe_prompt_payload, ensure_ascii=False))},
    )
    context.task_store.checkpoint(
        context.task_state,
        "prompt_rendered",
        {"promptTemplate": prompt_template, "agentStrategy": strategy_metadata, "responsesPayload": safe_prompt_payload},
        context.run_log.object_key,
    )

    game_id = str(uuid4())
    version_id = str(uuid4())
    use_static_generation = get_settings().create_static_generation
    cover_artifact: CoverAgentArtifact | None = None
    _update_job_stage(job_id, "generating", "static_generation" if use_static_generation else "llm_generation")
    context.run_log.append(
        stage="static_generation_started" if use_static_generation else "llm_generation_started",
        status="running",
        input_summary=("Static generation pipeline is starting." if use_static_generation else "LangGraph LLM generation is starting."),
        output_summary="Game and version identifiers allocated.",
        metrics={"gameId": game_id, "versionId": version_id, "staticGeneration": use_static_generation},
    )
    if use_static_generation:
        draft_pipeline = run_create_pipeline(
            prompt=cleaned_prompt,
            agent_mode=context.agent_mode,
            game_slug="pending",
            game_id=game_id,
            version_id=version_id,
            ai_config=ai_config,
            prompt_template=prompt_template,
            agent_strategy=strategy_metadata,
        )
        game_slug = f"{_slugify(draft_pipeline.title)}-{game_id[:8]}"
        pipeline = run_create_pipeline(
            prompt=cleaned_prompt,
            agent_mode=context.agent_mode,
            game_slug=game_slug,
            game_id=game_id,
            version_id=version_id,
            ai_config=ai_config,
            prompt_template=prompt_template,
            agent_strategy=strategy_metadata,
        )
        llm_metrics: dict[str, Any] = {}
        cover_artifact = None
    else:
        recorder = LLMCallRecorder(
            long_term_memory=context.long_term_memory,
            short_term_memory=context.short_term_memory,
            run_log=context.run_log,
        )
        graph_result = strategy.run_langgraph(
            settings=prompt_settings,
            model=ai_config["model"],
            adapter=_make_graph_adapter(ai_config),
            registry=build_builtin_tool_registry(),
            recorder=recorder,
        )
        if graph_result.messages:
            last_raw = graph_result.messages[-1].get("raw")
            if isinstance(last_raw, dict) and last_raw.get("ok") is False:
                if input_assets and _is_multimodal_unsupported_error(last_raw):
                    _cleanup_failed_input_assets(job_id=job_id, user_id=creator_id, input_assets=input_assets)
                    raise MultimodalUnsupportedError(
                        "MULTIMODAL_UNSUPPORTED: The configured API/model rejected image input. "
                        "Please switch to a vision-capable OpenAI Responses-compatible model or create without images."
                    )
                raise RuntimeError("The LLM provider call failed during generation.")
        last_message = graph_result.messages[-1] if graph_result.messages else {}
        llm_metrics = last_message.get("metrics") if isinstance(last_message.get("metrics"), dict) else {}
        parsed_output = parse_main_agent_json_output(_main_agent_output_value(graph_result))
        if parsed_output.get("fallback"):
            reason = str(parsed_output.get("fallbackReason") or "invalid_llm_output")
            raise RuntimeError(f"LLM output did not match the required game package contract: {reason}")
        draft_pipeline = build_pipeline_from_main_agent_output(
            prompt=cleaned_prompt,
            agent_mode=context.agent_mode,
            game_slug="pending",
            game_id=game_id,
            version_id=version_id,
            ai_config=ai_config,
            parsed_output=parsed_output,
            prompt_template=prompt_template,
            agent_strategy=strategy_metadata,
            llm_metrics=llm_metrics,
        )
        game_slug = f"{_slugify(draft_pipeline.title)}-{game_id[:8]}"
        pipeline = build_pipeline_from_main_agent_output(
            prompt=cleaned_prompt,
            agent_mode=context.agent_mode,
            game_slug=game_slug,
            game_id=game_id,
            version_id=version_id,
            ai_config=ai_config,
            parsed_output=parsed_output,
            prompt_template=prompt_template,
            agent_strategy=strategy_metadata,
            llm_metrics=llm_metrics,
        )
        cover_artifact = _generate_required_cover_artifact(
            ai_config=ai_config,
            context=context,
            cleaned_prompt=cleaned_prompt,
            pipeline=pipeline,
            parsed_output=parsed_output,
        )

    _publish_pipeline_for_existing_job(
        job_id=job_id,
        creator_id=creator_id,
        context=context,
        pipeline=pipeline,
        game_id=game_id,
        version_id=version_id,
        game_slug=game_slug,
        prompt_template=prompt_template,
        strategy_metadata=strategy_metadata,
        llm_metrics=llm_metrics,
        use_static_generation=use_static_generation,
        cover_artifact=cover_artifact,
    )


def _publish_pipeline_for_existing_job(
    *,
    job_id: str,
    creator_id: str,
    context: Any,
    pipeline: Any,
    game_id: str,
    version_id: str,
    game_slug: str,
    prompt_template: dict[str, Any],
    strategy_metadata: dict[str, Any],
    llm_metrics: dict[str, Any],
    use_static_generation: bool,
    cover_artifact: CoverAgentArtifact | None = None,
) -> None:
    agent_mode = pipeline.source["agentMode"]
    publish_artifacts = _publish_artifacts(
        pipeline=pipeline,
        cover_artifact=cover_artifact,
        use_static_generation=use_static_generation,
    )
    context.agent_mode = agent_mode
    context.short_term_memory.record_tool_call({"tool": "run_create_pipeline", "status": "succeeded", "agentMode": agent_mode})
    context.run_log.append(
        stage="static_generation_completed" if use_static_generation else "llm_generation_completed",
        status="succeeded",
        input_summary="Static pipeline returned generated artifacts." if use_static_generation else "LangGraph strategy returned generated artifacts.",
        output_summary=f"{len(publish_artifacts)} artifacts are ready for object storage.",
        metrics={
            "artifactCount": len(publish_artifacts),
            "runtime": pipeline.runtime,
            "staticGeneration": use_static_generation,
            "llmMetrics": llm_metrics,
            "coverAgent": bool(cover_artifact),
        },
    )
    context.task_store.checkpoint(
        context.task_state,
        "static_generation_completed" if use_static_generation else "llm_generation_completed",
        {
            "artifactCount": len(publish_artifacts),
            "runtime": pipeline.runtime,
            "staticGeneration": use_static_generation,
            "llmMetrics": llm_metrics,
            "coverAgent": bool(cover_artifact),
        },
        context.run_log.object_key,
    )

    _update_job_stage(job_id, "uploading", "object_storage")
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
    for artifact in publish_artifacts:
        object_key = f"{storage_prefix}/{artifact.filename}"
        stored_url = _put_object(object_key, artifact.content, artifact.content_type)
        public_url = document_url if artifact.filename == pipeline.entry_file else stored_url
        uploaded_artifacts.append((artifact, object_key, public_url))
        if artifact.kind == "cover":
            context.run_log.append(
                stage="cover_uploaded",
                status="succeeded",
                input_summary="Cover asset uploaded to MinIO.",
                output_summary="Cover is ready for dynamic catalog responses.",
                metrics={
                    "objectKey": object_key,
                    "contentType": artifact.content_type.split(";", 1)[0],
                    "sizeBytes": len(artifact.content),
                    "width": COVER_WIDTH,
                    "height": COVER_HEIGHT,
                },
            )
    context.short_term_memory.record_file_edit(
        {"operation": "upload_artifacts", "storagePrefix": storage_prefix, "artifactCount": len(uploaded_artifacts) + 1}
    )
    context.run_log.append(
        stage="objects_uploaded",
        status="succeeded",
        input_summary="Generated objects uploaded to MinIO.",
        output_summary="Manifest and playable artifacts have object keys.",
        metrics={"storagePrefix": storage_prefix, "manifestObjectKey": manifest_key, "artifactCount": len(uploaded_artifacts)},
    )

    _update_job_stage(job_id, "building", "sql_persist")
    with db_connection() as connection:
        [
            _insert_agent_log(connection, job_id, run.stage, run.status, run.input_summary, run.output_summary, run.log)
            for run in pipeline.runs
        ]
        game = connection.execute(
            """
INSERT INTO games (
  id, slug, author_id, title, description, visibility, publish_status, metadata, published_at
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
                Jsonb({"section": "Recently Created", "createdBy": "static-create" if use_static_generation else "llm-create", "agentMode": agent_mode}),
            ),
        ).fetchone()
        version = connection.execute(
            """
INSERT INTO game_versions (
  id, game_id, version_no, source_job_id, runtime, entry_file, build_status, safety_status, storage_prefix, metadata
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
                Jsonb({"stubbed": use_static_generation, "agentMode": agent_mode, "llmMetrics": llm_metrics}),
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

        if not use_static_generation and cover_asset_id is None:
            raise RuntimeError("Cover Agent asset was not persisted; refusing to publish the game.")

        connection.execute("UPDATE game_versions SET manifest_asset_id = %s WHERE id = %s", (manifest_asset["id"], version["id"]))
        connection.execute("UPDATE games SET current_version_id = %s, cover_asset_id = %s WHERE id = %s", (version["id"], cover_asset_id, game_id))
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
        _insert_agent_log(
            connection,
            job_id,
            "publisher",
            "succeeded",
            "Uploaded generated game files to MinIO and persisted SQL metadata.",
            "Game is published and ready for iframe play.",
            {"stubbed": use_static_generation, "agentMode": agent_mode, "bundleUrl": bundle_public_url, "manifestUrl": manifest_public_url},
        )

    context.run_log.append(
        stage="sql_persisted",
        status="succeeded",
        input_summary="Generated game metadata persisted to PostgreSQL.",
        output_summary="Job, game, version, assets, artifacts, and legacy agent logs are linked.",
        metrics={"jobId": job_id, "gameSlug": game_slug, "assetCount": len(artifact_asset_ids) + 1},
    )
    recent = RecentGame(gameId=game_id, gameSlug=game_slug, title=game["title"], playUrl=f"/play/{game_slug}", jobId=job_id)
    _cache_recent_game(creator_id, recent)
    summary = {
        "title": game["title"],
        "gameSlug": game_slug,
        "playUrl": f"/play/{game_slug}",
        "manifestUrl": f"/play/{game_slug}/manifest",
        "coverUrl": next((public_url for artifact, _object_key, public_url in uploaded_artifacts if artifact.kind == "cover"), None),
        "storagePrefix": storage_prefix,
        "implementationPath": [record["stage"] for record in context.run_log.records],
        "effectSummary": {
            "runtime": pipeline.runtime,
            "entryFile": pipeline.entry_file,
            "artifactCount": len(uploaded_artifacts) + 1,
            "stubbed": use_static_generation,
            "staticGeneration": use_static_generation,
            "coverAgent": bool(cover_artifact),
        },
        "promptTemplate": prompt_template,
        "agentStrategy": strategy_metadata,
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
    context.short_term_memory.record_test({"name": "create_generation", "status": "succeeded"})
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


def create_generation_job(
    creator_id: str,
    prompt: str,
    files: list[str],
    input_assets: list[CreateInputAsset | dict[str, Any]] | None = None,
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
    resolved_input_assets = _load_create_input_assets(creator_id, input_assets)
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
    tool_metadata = list_builtin_tool_metadata()
    prompt_settings = AgentRequestSettings.from_create_context(
        user_request=cleaned_prompt,
        create_type=context.create_type,
        agent_mode=agent_mode,
        recent_8_history=context.long_term_memory.snapshot().get("history", []),
        workspace_capability=context.workspace.capability,
        workspace_boundary=context.workspace.worktree_stub_path,
        persistent_memory_summary=context.persistent_memory.list(
            user_id=creator_id,
            project_id=context.project_id,
        ),
        tool_metadata=tool_metadata,
        input_assets=_assets_for_prompt(resolved_input_assets),
    )
    prompt_tool_result = build_builtin_tool_registry().call(
        "llm.prompt_render",
        {
            "userRequest": prompt_settings.user_request,
            "createType": prompt_settings.create_type,
            "agentMode": prompt_settings.agent_mode,
            "recent8History": prompt_settings.recent_8_history,
            "workspaceCapability": prompt_settings.workspace_capability,
            "workspaceBoundary": prompt_settings.workspace_boundary,
            "persistentMemorySummary": prompt_settings.persistent_memory_summary,
            "toolMetadata": tool_metadata,
            "inputAssets": prompt_settings.input_assets,
            "model": ai_config["model"],
        },
    )
    context.short_term_memory.record_tool_call(
        {
            "tool": "llm.prompt_render",
            "status": "succeeded" if prompt_tool_result["ok"] else "failed",
            "dryRun": True,
        }
    )
    if not prompt_tool_result["ok"] or "payload" not in prompt_tool_result.get("data", {}):
        context.run_log.append(
            stage="prompt_render_failed",
            status="failed",
            input_summary="Create prompt payload could not be rendered.",
            output_summary=str(prompt_tool_result.get("error") or "Unknown prompt render failure")[:500],
            metrics={"toolResult": prompt_tool_result},
        )
        finalize_agent_run(
            context=context,
            status_value="failed",
            summary={"error": prompt_tool_result.get("error"), "stage": "prompt_render_failed"},
            final_answer="Prompt rendering failed before generation could start.",
        )
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail={
                "code": "PROMPT_RENDER_FAILED",
                "message": "Create prompt rendering failed.",
                "tool": prompt_tool_result.get("error"),
            },
        )
    prompt_payload = prompt_tool_result["data"]["payload"]
    safe_prompt_payload = _redacted_prompt_payload(prompt_payload)
    prompt_template = template_metadata(prompt_payload)
    strategy = select_agent_strategy(prompt_settings)
    strategy_plan = strategy.plan(prompt_settings)
    strategy_metadata = strategy_plan.to_metadata()
    context.run_log.append(
        stage="agent_strategy_selected",
        status="succeeded",
        input_summary="Backend selected the agent strategy from createType and agentMode.",
        output_summary=f"{strategy_metadata['strategy']} strategy framework selected.",
        metrics=strategy_metadata,
    )
    context.run_log.append(
        stage="prompt_rendered",
        status="succeeded",
        input_summary="Create game prompt template rendered.",
        output_summary=f"{CREATE_GAME_TEMPLATE_NAME}@{CREATE_GAME_TEMPLATE_VERSION} is ready for future LLM generation.",
        metrics={
            **prompt_template,
            "strategy": strategy_metadata,
            "renderedCharacters": len(json.dumps(safe_prompt_payload, ensure_ascii=False)),
        },
    )
    context.task_store.checkpoint(
        context.task_state,
        "prompt_rendered",
        {"promptTemplate": prompt_template, "agentStrategy": strategy_metadata, "responsesPayload": safe_prompt_payload},
        context.run_log.object_key,
    )
    game_id = str(uuid4())
    version_id = str(uuid4())
    use_static_generation = get_settings().create_static_generation
    generation_stage = "static_generation_started" if use_static_generation else "llm_generation_started"
    context.run_log.append(
        stage=generation_stage,
        status="running",
        input_summary=("Static generation pipeline is starting." if use_static_generation else "LangGraph LLM generation is starting."),
        output_summary="Game and version identifiers allocated.",
        metrics={"gameId": game_id, "versionId": version_id, "staticGeneration": use_static_generation},
    )
    if use_static_generation:
        draft_pipeline = run_create_pipeline(
            prompt=cleaned_prompt,
            agent_mode=agent_mode,
            game_slug="pending",
            game_id=game_id,
            version_id=version_id,
            ai_config=ai_config,
            prompt_template=prompt_template,
            agent_strategy=strategy_metadata,
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
            agent_strategy=strategy_metadata,
        )
        llm_metrics: dict[str, Any] = {}
    else:
        recorder = LLMCallRecorder(
            long_term_memory=context.long_term_memory,
            short_term_memory=context.short_term_memory,
            run_log=context.run_log,
        )
        graph_result = strategy.run_langgraph(
            settings=prompt_settings,
            model=ai_config["model"],
            adapter=_make_graph_adapter(ai_config),
            registry=build_builtin_tool_registry(),
            recorder=recorder,
        )
        if graph_result.messages:
            last_raw = graph_result.messages[-1].get("raw")
            if isinstance(last_raw, dict) and last_raw.get("ok") is False:
                context.run_log.append(
                    stage="llm_generation_failed",
                    status="failed",
                    input_summary="LLM provider call failed during LangGraph generation.",
                    output_summary=str(last_raw.get("error") or last_raw)[:500],
                    metrics={"raw": last_raw},
                )
                finalize_agent_run(
                    context=context,
                    status_value="failed",
                    summary={"error": last_raw, "stage": "llm_generation_failed"},
                    final_answer="LLM generation failed before a playable game could be produced.",
                )
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail={
                        "code": "LLM_GENERATION_FAILED",
                        "message": "The LLM provider call failed during generation.",
                        "llm": last_raw,
                    },
                )
        last_message = graph_result.messages[-1] if graph_result.messages else {}
        llm_metrics = last_message.get("metrics") if isinstance(last_message.get("metrics"), dict) else {}
        parsed_output = parse_main_agent_json_output(_main_agent_output_value(graph_result))
        if parsed_output.get("fallback"):
            context.run_log.append(
                stage="llm_output_fallback",
                status="succeeded",
                input_summary="LLM output did not fully match the game package contract.",
                output_summary="Backend fallback output parser produced a safe minimal game package.",
                metrics={"fallbackReason": parsed_output.get("fallbackReason"), "finishReason": graph_result.finish_reason},
            )
        draft_pipeline = build_pipeline_from_main_agent_output(
            prompt=cleaned_prompt,
            agent_mode=agent_mode,
            game_slug="pending",
            game_id=game_id,
            version_id=version_id,
            ai_config=ai_config,
            parsed_output=parsed_output,
            prompt_template=prompt_template,
            agent_strategy=strategy_metadata,
            llm_metrics=llm_metrics,
        )
        game_slug = f"{_slugify(draft_pipeline.title)}-{game_id[:8]}"
        pipeline = build_pipeline_from_main_agent_output(
            prompt=cleaned_prompt,
            agent_mode=agent_mode,
            game_slug=game_slug,
            game_id=game_id,
            version_id=version_id,
            ai_config=ai_config,
            parsed_output=parsed_output,
            prompt_template=prompt_template,
            agent_strategy=strategy_metadata,
            llm_metrics=llm_metrics,
        )
    agent_mode = pipeline.source["agentMode"]
    context.agent_mode = agent_mode
    context.short_term_memory.record_tool_call(
        {"tool": "run_create_pipeline", "status": "succeeded", "agentMode": agent_mode}
    )
    context.run_log.append(
        stage="static_generation_completed" if use_static_generation else "llm_generation_completed",
        status="succeeded",
        input_summary="Static pipeline returned generated artifacts." if use_static_generation else "LangGraph strategy returned generated artifacts.",
        output_summary=f"{len(pipeline.artifacts)} artifacts are ready for object storage.",
        metrics={
            "artifactCount": len(pipeline.artifacts),
            "runtime": pipeline.runtime,
            "staticGeneration": use_static_generation,
            "llmMetrics": llm_metrics,
        },
    )
    context.task_store.checkpoint(
        context.task_state,
        "static_generation_completed" if use_static_generation else "llm_generation_completed",
        {
            "artifactCount": len(pipeline.artifacts),
            "runtime": pipeline.runtime,
            "staticGeneration": use_static_generation,
            "llmMetrics": llm_metrics,
        },
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
                        "agentStrategy": strategy_metadata,
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
                Jsonb({"section": "Recently Created", "createdBy": "static-create" if use_static_generation else "llm-create", "agentMode": agent_mode}),
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
                Jsonb({"stubbed": use_static_generation, "agentMode": agent_mode, "llmMetrics": llm_metrics}),
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
                    "stubbed": use_static_generation,
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
            "stubbed": use_static_generation,
            "staticGeneration": use_static_generation,
        },
        "promptTemplate": prompt_template,
        "agentStrategy": strategy_metadata,
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

