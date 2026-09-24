from __future__ import annotations

import hashlib
import json
import re
import base64
from datetime import datetime, timezone
from html.parser import HTMLParser
from io import BytesIO
from pathlib import Path, PurePosixPath
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
from app.agents.decentralized import (
    confirm_decentralized_run,
    generate_decentralized_previews,
    get_decentralized_previews,
    select_decentralized_candidate,
)
from app.agents.decentralized.orchestrator import build_decentralized_final_result
from app.agents.decentralized.storage import clear_decentralized_cache
from app.agents.framework import create_agent_run_context, finalize_agent_run, load_agent_run_context_for_job
from app.agents.framework.workspace import WorkspaceFS
from app.agents.framework.schema import ensure_agent_framework_schema
from app.agents.graphs.errors import LLMProviderCallError, provider_error_diagnostics
from app.agents.graphs.llm_adapter import OpenAIResponsesGraphAdapter
from app.agents.graphs.recording import LLMCallRecorder
from app.agents.multi_agent import record_multi_agent_contracts
from app.agents.prompts import (
    CREATE_GAME_TEMPLATE_NAME,
    CREATE_GAME_TEMPLATE_VERSION,
    template_metadata,
)
from app.agents.strategies import AgentRequestSettings, select_agent_strategy
from app.agents.tools import build_builtin_tool_registry, list_builtin_tool_metadata
from app.config import get_settings
from app.database import db_connection
from app.schemas import (
    AIConfigRequest,
    AIConfigState,
    AIConfigTestRequest,
    AgentLog,
    CreateInputAsset,
    CreateJob,
    CreateProjectDeleteResult,
    LLMTestResult,
    RecentGame,
    UserProfile,
)
from app.services.auth_service import redis_client
from app.services.llm_service import test_llm_config

AI_CONFIG_KEY_PREFIX = "create:ai-config:"
RECENT_GAME_KEY_PREFIX = "create:recent-game:"
PLAN_APPROVAL_KEY_PREFIX = "create:plan-approval:"
PLAN_APPROVAL_TTL_SECONDS = 60 * 60 * 24
_AI_CONFIG_SCHEMA_READY = False


class MultimodalUnsupportedError(RuntimeError):
    pass


class CreateLLMGenerationError(RuntimeError):
    def __init__(self, message: str, diagnostics: dict[str, Any] | None = None):
        self.diagnostics = diagnostics or {}
        super().__init__(message)


class PublishHtmlSafetyParser(HTMLParser):
    BLOCKED_TAGS = {"iframe", "object", "embed", "link", "base", "form"}
    URL_ATTRS = {"src", "href", "action", "formaction", "poster"}

    def __init__(self, filename: str) -> None:
        super().__init__(convert_charrefs=True)
        self.filename = filename
        self.issues: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._scan_tag(tag, attrs)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._scan_tag(tag, attrs)

    def _scan_tag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag in self.BLOCKED_TAGS:
            self.issues.append({"code": "BLOCKED_HTML_TAG", "message": f"{self.filename} contains blocked tag: {normalized_tag}"})
        for raw_name, raw_value in attrs:
            name = raw_name.lower()
            value = (raw_value or "").strip().lower()
            if name.startswith("on"):
                self.issues.append({"code": "INLINE_EVENT_HANDLER_BLOCKED", "message": f"{self.filename} contains inline event handler: {name}"})
            if name in {"integrity", "nonce"}:
                self.issues.append({"code": "CSP_BYPASS_ATTRIBUTE_BLOCKED", "message": f"{self.filename} contains blocked attribute: {name}"})
            if name in self.URL_ATTRS:
                if value.startswith(("http://", "https://", "//")):
                    self.issues.append({"code": "REMOTE_RESOURCE_BLOCKED", "message": f"{self.filename} references remote resource in {name}."})
                if value.startswith(("javascript:", "data:text/html", "file:", "blob:")):
                    self.issues.append({"code": "DANGEROUS_URL_BLOCKED", "message": f"{self.filename} contains dangerous URL in {name}."})


_ALLOWED_PARENT_POST_MESSAGE_RE = re.compile(r"\bwindow\s*\.\s*parent\s*\.\s*postmessage\s*\(", re.IGNORECASE)
_WINDOW_PARENT_ACCESS_RE = re.compile(r"\bwindow\s*(?:\??\.\s*parent\b|\[\s*['\"]parent['\"]\s*\])", re.IGNORECASE)
_PARENT_ALIAS_ACCESS_RE = re.compile(
    r"(?<![\w$.])parent\s*(?:\.\s*|\[\s*['\"])(?:postmessage|location|document|frames|top|opener|history)\b",
    re.IGNORECASE,
)
_INDIRECT_PARENT_ACCESS_RE = re.compile(
    r"\b(?:self|globalthis)\s*\.\s*parent\b",
    re.IGNORECASE,
)


def _html_has_blocked_parent_access(html: str) -> bool:
    """Allow Gameweare iframe lifecycle messaging while blocking direct parent access."""
    without_allowed_post_message = _ALLOWED_PARENT_POST_MESSAGE_RE.sub("(", html)
    return bool(
        _WINDOW_PARENT_ACCESS_RE.search(without_allowed_post_message)
        or _PARENT_ALIAS_ACCESS_RE.search(without_allowed_post_message)
        or _INDIRECT_PARENT_ACCESS_RE.search(without_allowed_post_message)
    )


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
        playUrl=f"/play/{row['game_slug']}" if row.get("game_slug") and not row.get("deleted_at") else None,
        manifestUrl=f"/play/{row['game_slug']}/manifest" if row.get("game_slug") and not row.get("deleted_at") else None,
        publishStatus="draft" if row.get("version_id") and row.get("current_stage") != "published" else row.get("publish_status"),
        visibility=row.get("visibility"),
        versionNo=row.get("version_no"),
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


def _ai_config_session_cache_key(user_id: str) -> str:
    return _ai_config_cache_key(user_id, None)


def _recent_game_cache_key(user_id: str) -> str:
    return f"{RECENT_GAME_KEY_PREFIX}{user_id}"


def _plan_approval_cache_key(run_id: str) -> str:
    return f"{PLAN_APPROVAL_KEY_PREFIX}{run_id}"


def _cache_ai_config(user_id: str, jwt_jti: str | None, payload: dict[str, str]) -> None:
    ttl = get_settings().jwt_ttl_seconds
    serialized = json.dumps(payload)
    client = redis_client()
    client.setex(_ai_config_session_cache_key(user_id), ttl, serialized)
    if jwt_jti:
        client.setex(_ai_config_cache_key(user_id, jwt_jti), ttl, serialized)


def _clear_ai_config_cache(user_id: str) -> None:
    client = redis_client()
    for cache_key in list(client.scan_iter(f"{AI_CONFIG_KEY_PREFIX}{user_id}:*")):
        client.delete(cache_key)


def _cached_ai_config(user_id: str, jwt_jti: str | None = None) -> dict[str, str] | None:
    client = redis_client()
    cache_keys = [_ai_config_cache_key(user_id, jwt_jti)]
    session_key = _ai_config_session_cache_key(user_id)
    if session_key not in cache_keys:
        cache_keys.append(session_key)
    for cache_key in cache_keys:
        cached = client.get(cache_key)
        if not cached:
            continue
        try:
            payload = json.loads(cached)
        except json.JSONDecodeError:
            continue
        if payload.get("baseUrl") and payload.get("model") and payload.get("apiKey"):
            if jwt_jti and cache_key != _ai_config_cache_key(user_id, jwt_jti):
                _cache_ai_config(user_id, jwt_jti, payload)
            return payload
    return None


def _ai_config_public_state(config: dict[str, str] | None) -> AIConfigState:
    if not config:
        return AIConfigState(authenticated=True, configured=False, staticGeneration=get_settings().create_static_generation)
    return AIConfigState(
        authenticated=True,
        configured=True,
        provider=config.get("provider"),
        staticGeneration=get_settings().create_static_generation,
    )


def get_ai_config_state(user: UserProfile | None, jwt_jti: str | None = None) -> AIConfigState:
    if not user:
        return AIConfigState(authenticated=False, configured=False, staticGeneration=get_settings().create_static_generation)
    ensure_create_runtime_schema()

    cached = _cached_ai_config(user.id, jwt_jti)
    if cached:
        return _ai_config_public_state(cached)

    config = _load_ai_config(user.id, jwt_jti)
    if not config:
        return _ai_config_public_state(None)
    return _ai_config_public_state(config)


def warm_ai_config_cache(user_id: str, jwt_jti: str | None = None) -> bool:
    try:
        return _load_ai_config(user_id, jwt_jti) is not None
    except Exception:
        return False


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

    _clear_ai_config_cache(user_id)
    _cache_ai_config(
        user_id,
        jwt_jti,
        {"baseUrl": base_url, "model": model, "provider": provider, "apiKey": api_key},
    )
    return _ai_config_public_state({"baseUrl": base_url, "model": model, "provider": provider, "apiKey": api_key})


def test_saved_or_payload_ai_config(user_id: str, payload: AIConfigTestRequest | None = None, jwt_jti: str | None = None) -> LLMTestResult:
    if payload and payload.baseUrl and payload.model and payload.apiKey:
        return test_llm_config(
            base_url=payload.baseUrl,
            model=payload.model,
            api_key=payload.apiKey,
        )
    config = _load_ai_config(user_id, jwt_jti)
    if not config:
        return LLMTestResult(
            ok=False,
            code="missing_ai_config",
            message="AI configuration is required before testing.",
            details={},
        )
    return test_llm_config(
        base_url=config["baseUrl"],
        model=config["model"],
        api_key=config["apiKey"],
    )


def _load_ai_config(user_id: str, jwt_jti: str | None = None) -> dict[str, str] | None:
    ensure_create_runtime_schema()
    cached = _cached_ai_config(user_id, jwt_jti)
    if cached:
        return cached

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


def _read_minio_text(object_key: str, *, max_chars: int = 160_000) -> str:
    response = _minio_client().get_object(get_settings().minio_bucket, object_key)
    try:
        content = response.read()
    finally:
        response.close()
        response.release_conn()
    return content.decode("utf-8", errors="replace")[:max_chars]


def _artifact_filename_from_key(object_key: str) -> str:
    name = PurePosixPath(object_key.replace("\\", "/")).name
    return name or "artifact.txt"


def _latest_provider_error(messages: list[dict[str, Any]]) -> dict[str, Any] | None:
    for message in reversed(messages or []):
        raw = message.get("raw") if isinstance(message, dict) else None
        diagnostics = provider_error_diagnostics(raw if isinstance(raw, dict) else None)
        if diagnostics:
            return diagnostics
        direct = message.get("providerError") if isinstance(message, dict) else None
        if isinstance(direct, dict):
            return direct
    return None


def _load_project_game_for_write(*, connection: Connection, user_id: str, project_id: str) -> dict[str, Any] | None:
    return connection.execute(
        """
SELECT
  p.id AS project_id,
  p.game_id,
  g.slug,
  g.title,
  g.description,
  g.cover_asset_id,
  g.current_version_id,
  g.metadata,
  g.publish_status,
  g.visibility,
  g.deleted_at,
  COALESCE(MAX(gv.version_no), 0) AS max_version_no
FROM agent_projects p
LEFT JOIN games g ON g.id = p.game_id
LEFT JOIN game_versions gv ON gv.game_id = g.id
WHERE p.id = %s AND p.user_id = %s AND p.status = 'active' AND (g.id IS NULL OR g.deleted_at IS NULL)
GROUP BY p.id, p.game_id, g.slug, g.title, g.description, g.cover_asset_id, g.current_version_id, g.metadata, g.publish_status, g.visibility, g.deleted_at
LIMIT 1
""",
        (project_id, user_id),
    ).fetchone()


def _prune_old_game_versions(connection: Connection, *, game_id: str, keep: int = 2) -> None:
    current = connection.execute("SELECT current_version_id FROM games WHERE id = %s LIMIT 1", (game_id,)).fetchone()
    current_version_id = str(current["current_version_id"]) if current and current["current_version_id"] else None
    rows = connection.execute(
        """
SELECT id
FROM game_versions
WHERE game_id = %s
ORDER BY version_no DESC
""",
        (game_id,),
    ).fetchall()
    keep_ids: set[str] = set()
    if current_version_id:
        keep_ids.add(current_version_id)
    for row in rows:
        if len(keep_ids) >= keep:
            break
        keep_ids.add(str(row["id"]))
    version_ids = [row["id"] for row in rows if str(row["id"]) not in keep_ids]
    if not version_ids:
        return
    asset_rows = connection.execute(
        """
SELECT id, bucket, object_key
FROM assets
WHERE version_id = ANY(%s)
""",
        (version_ids,),
    ).fetchall()
    client = _minio_client()
    for asset in asset_rows:
        if asset["bucket"] != "external" and asset["object_key"]:
            try:
                client.remove_object(asset["bucket"], asset["object_key"])
            except Exception:
                pass
    connection.execute("DELETE FROM job_artifacts WHERE asset_id = ANY(%s)", ([asset["id"] for asset in asset_rows],))
    connection.execute("DELETE FROM assets WHERE version_id = ANY(%s)", (version_ids,))
    connection.execute("DELETE FROM game_versions WHERE id = ANY(%s)", (version_ids,))


def _allocate_project_game_version(*, creator_id: str, context: Any, title_hint: str = "generated-game") -> dict[str, Any]:
    with db_connection() as connection:
        existing = _load_project_game_for_write(connection=connection, user_id=creator_id, project_id=context.project_id)
    if context.create_type == "opt":
        if not existing or not existing["game_id"]:
            raise RuntimeError("Cannot optimize this project because no draft or published game record exists.")
        return {
            "gameId": str(existing["game_id"]),
            "gameSlug": existing["slug"],
            "versionId": str(uuid4()),
            "versionNo": int(existing["max_version_no"] or 0) + 1,
            "existingGame": dict(existing),
        }

    game_id = str(uuid4())
    return {
        "gameId": game_id,
        "gameSlug": f"{_slugify(title_hint)}-{game_id[:8]}",
        "versionId": str(uuid4()),
        "versionNo": 1,
        "existingGame": None,
    }


def _load_project_refinement_artifacts(*, user_id: str, project_id: str) -> dict[str, Any] | None:
    with db_connection() as connection:
        rows = connection.execute(
            """
SELECT
  g.id AS game_id,
  g.slug,
  g.title,
  g.description,
  gv.id AS version_id,
  gv.version_no,
  gv.entry_file,
  a.kind,
  a.object_key,
  a.public_url,
  a.content_type,
  a.size_bytes,
  a.sha256
FROM agent_projects p
JOIN games g ON g.id = p.game_id
JOIN LATERAL (
  SELECT gv_inner.*
  FROM game_versions gv_inner
  WHERE gv_inner.game_id = g.id
  ORDER BY gv_inner.version_no DESC, gv_inner.created_at DESC
  LIMIT 1
) gv ON true
LEFT JOIN assets a ON (
  a.version_id = gv.id OR a.id = gv.manifest_asset_id
)
WHERE
  p.id = %s
  AND p.user_id = %s
  AND p.status = 'active'
  AND a.kind IN ('bundle', 'source', 'manifest')
ORDER BY
  CASE a.kind
    WHEN 'bundle' THEN 1
    WHEN 'source' THEN 2
    WHEN 'manifest' THEN 3
    ELSE 4
  END,
  a.created_at DESC
""",
            (project_id, user_id),
        ).fetchall()
    if not rows:
        return None

    first = rows[0]
    files: dict[str, str] = {}
    artifacts: list[dict[str, Any]] = []
    for row in rows:
        object_key = row["object_key"]
        if not object_key:
            continue
        filename = _artifact_filename_from_key(object_key)
        if row["kind"] == "bundle":
            filename = str(first["entry_file"] or filename or "index.html")
        elif row["kind"] == "source":
            filename = "source.json"
        elif row["kind"] == "manifest":
            filename = "manifest.json"
        if filename in files:
            continue
        try:
            content = _read_minio_text(object_key)
        except Exception:
            continue
        files[filename] = content
        artifacts.append(
            {
                "kind": row["kind"],
                "path": filename,
                "objectKey": object_key,
                "publicUrl": row["public_url"],
                "contentType": row["content_type"],
                "sizeBytes": int(row["size_bytes"] or 0),
                "sha256": row["sha256"],
                "availableInWorkspace": bool(content),
            }
        )

    return {
        "gameId": str(first["game_id"]),
        "gameSlug": first["slug"],
        "title": first["title"],
        "description": first["description"],
        "versionId": str(first["version_id"]),
        "versionNo": int(first["version_no"]),
        "entryFile": first["entry_file"],
        "files": files,
        "artifacts": artifacts,
    }


def get_project_preview(user_id: str, project_id: str) -> dict[str, Any]:
    previous = _load_project_refinement_artifacts(user_id=user_id, project_id=project_id)
    if not previous:
        raise HTTPException(status_code=404, detail={"code": "PROJECT_PREVIEW_NOT_FOUND", "message": "No playable version was found for this project."})
    html = previous.get("files", {}).get(str(previous.get("entryFile") or "index.html")) or previous.get("files", {}).get("index.html")
    if not isinstance(html, str) or not html.strip():
        raise HTTPException(status_code=404, detail={"code": "PROJECT_PREVIEW_NOT_FOUND", "message": "The latest project version has no readable HTML document."})
    source: dict[str, Any] = {}
    raw_source = previous.get("files", {}).get("source.json")
    if isinstance(raw_source, str) and raw_source.strip():
        try:
            loaded = json.loads(raw_source)
            if isinstance(loaded, dict):
                source = loaded
        except json.JSONDecodeError:
            source = {"rawSourcePreview": raw_source[:1000]}
    return {
        "projectId": project_id,
        "gameId": previous["gameId"],
        "gameSlug": previous["gameSlug"],
        "title": previous["title"],
        "description": previous["description"],
        "versionId": previous["versionId"],
        "versionNo": previous["versionNo"],
        "entryFile": str(previous.get("entryFile") or "index.html"),
        "html": html,
        "source": source,
    }


def delete_create_project(user_id: str, project_id: str) -> CreateProjectDeleteResult | None:
    ensure_create_runtime_schema()
    with db_connection() as connection:
        project = connection.execute(
            """
SELECT
  p.id AS project_id,
  p.game_id,
  p.status,
  g.slug AS game_slug,
  g.deleted_at
FROM agent_projects p
LEFT JOIN games g ON g.id = p.game_id
WHERE p.id = %s AND p.user_id = %s AND p.status <> 'deleted'
LIMIT 1
""",
            (project_id, user_id),
        ).fetchone()
        if not project:
            return None

        game_id = str(project["game_id"]) if project["game_id"] else None
        game_slug = project["game_slug"]
        run_rows = connection.execute(
            """
SELECT id
FROM create_runs
WHERE project_id = %s AND user_id = %s
""",
            (project_id, user_id),
        ).fetchall()
        if game_id and not project["deleted_at"]:
            connection.execute(
                """
UPDATE games
SET
  visibility = 'private',
  publish_status = 'archived',
  deleted_at = COALESCE(deleted_at, now()),
  updated_at = now(),
  metadata = metadata || %s
WHERE id = %s AND author_id = %s
""",
                (Jsonb({"deletedByCreator": True, "deletedViaProject": True, "runLogsPreserved": True}), game_id, user_id),
            )
            connection.execute("DELETE FROM game_likes WHERE game_id = %s", (game_id,))
            connection.execute("DELETE FROM game_favorites WHERE game_id = %s", (game_id,))
            connection.execute(
                """
UPDATE game_comments
SET status = 'deleted', deleted_at = COALESCE(deleted_at, now())
WHERE game_id = %s AND status <> 'deleted'
""",
                (game_id,),
            )

        connection.execute(
            """
UPDATE agent_projects
SET
  status = 'deleted',
  metadata = metadata || %s,
  updated_at = now()
WHERE id = %s AND user_id = %s AND status <> 'deleted'
""",
            (
                Jsonb(
                    {
                        "deletedByCreator": True,
                        "deletedAt": datetime.now(timezone.utc).isoformat(),
                        "deletedGameId": game_id,
                        "deletedGameSlug": game_slug,
                        "runLogsPreserved": True,
                    }
                ),
                project_id,
                user_id,
            ),
        )
        connection.execute(
            """
UPDATE generation_jobs
SET status = 'canceled', current_stage = 'deleted_by_creator', completed_at = COALESCE(completed_at, now()), updated_at = now()
WHERE creator_id = %s
  AND input_payload->>'projectId' = %s
  AND status IN ('pending', 'planning', 'generating', 'building', 'reviewing', 'uploading')
""",
            (user_id, project_id),
        )
        connection.execute(
            """
UPDATE create_runs
SET
  status = 'canceled',
  completed_at = COALESCE(completed_at, now()),
  summary = summary || %s,
  updated_at = now()
WHERE project_id = %s
  AND user_id = %s
  AND status = 'running'
""",
            (Jsonb({"deletedByCreator": True, "runLogsPreserved": True}), project_id, user_id),
        )
    client = redis_client()
    client.delete(_recent_game_cache_key(user_id))
    for row in run_rows:
        run_id = str(row["id"])
        client.delete(_plan_approval_cache_key(run_id))
        clear_decentralized_cache(run_id)
    return CreateProjectDeleteResult(
        projectId=project_id,
        gameId=game_id,
        gameSlug=game_slug,
        deleted=True,
        runLogsPreserved=True,
    )


def _prepare_opt_workspace_context(*, context: Any, user_id: str) -> list[dict[str, Any]]:
    if context.create_type != "opt":
        return []

    previous = _load_project_refinement_artifacts(user_id=user_id, project_id=context.project_id)
    if not previous or not previous.get("files"):
        context.run_log.append(
            stage="refinement_context_missing",
            status="failed",
            input_summary="Continue optimization requested existing project artifacts.",
            output_summary="No draft or published game artifacts were found for this project.",
            metrics={"projectId": context.project_id},
        )
        raise RuntimeError("Cannot optimize this project because no previous game artifacts were found.")

    Path(context.workspace.worktree_stub_path).mkdir(parents=True, exist_ok=True)
    fs = WorkspaceFS(context.workspace)
    for path, content in previous["files"].items():
        fs.write_text(path, content)

    summary = {
        "type": "existing_project_artifacts",
        "summary": "Previous draft or published game artifacts are available in the workspace for optimization.",
        "gameSlug": previous["gameSlug"],
        "title": previous["title"],
        "description": previous["description"],
        "versionNo": previous["versionNo"],
        "entryFile": previous["entryFile"],
        "workspaceFiles": sorted(previous["files"].keys()),
        "artifacts": previous["artifacts"],
        "previousIndexHtmlPrefix": str(previous["files"].get("index.html") or "")[:4000],
        "previousSourceJson": str(previous["files"].get("source.json") or "")[:3000],
    }
    context.run_log.append(
        stage="refinement_context_loaded",
        status="succeeded",
        input_summary="Loaded previous project artifacts for continue optimization.",
        output_summary=f"{len(previous['files'])} file(s) are available in the run workspace.",
        metrics={
            "gameSlug": previous["gameSlug"],
            "versionNo": previous["versionNo"],
            "workspaceFiles": sorted(previous["files"].keys()),
        },
    )
    context.short_term_memory.record_file_edit(
        {"operation": "hydrate_opt_workspace", "files": sorted(previous["files"].keys()), "gameSlug": previous["gameSlug"]}
    )
    return [summary]


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


def get_plan_preview(user_id: str, run_id: str) -> dict[str, Any]:
    ensure_create_runtime_schema()
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT r.id, r.agent_mode, r.summary, r.job_id
FROM create_runs r
WHERE r.id = %s AND r.user_id = %s
LIMIT 1
""",
            (run_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["agent_mode"] != "plan":
        raise HTTPException(status_code=409, detail={"code": "NOT_PLAN_RUN", "message": "Run is not a plan strategy run."})
    summary = row["summary"] if isinstance(row["summary"], dict) else {}
    preview = summary.get("planPreview") if isinstance(summary.get("planPreview"), dict) else None
    if not preview:
        cached = redis_client().get(_plan_approval_cache_key(run_id))
        if cached:
            try:
                cached_payload = json.loads(cached)
            except json.JSONDecodeError:
                cached_payload = {}
            preview = cached_payload.get("planPreview") if isinstance(cached_payload.get("planPreview"), dict) else None
    if not preview:
        raise HTTPException(status_code=404, detail="Plan preview not found")
    return {
        "runId": run_id,
        "jobId": str(row["job_id"]) if row["job_id"] else None,
        "phase": summary.get("phase"),
        "planPreview": preview,
    }


def decide_plan_run(user_id: str, run_id: str, decision: str, jwt_jti: str | None = None) -> CreateJob:
    ensure_create_runtime_schema()
    normalized = decision.strip().lower()
    if normalized not in {"accepted", "rejected"}:
        raise HTTPException(status_code=400, detail={"code": "INVALID_PLAN_DECISION", "message": "Decision must be accepted or rejected."})
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT r.id, r.agent_mode, r.status, r.summary, r.job_id, r.project_id, r.create_type, j.creator_id
FROM create_runs r
JOIN generation_jobs j ON j.id = r.job_id
WHERE r.id = %s AND r.user_id = %s
LIMIT 1
""",
            (run_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["agent_mode"] != "plan":
        raise HTTPException(status_code=409, detail={"code": "NOT_PLAN_RUN", "message": "Run is not a plan strategy run."})
    summary = row["summary"] if isinstance(row["summary"], dict) else {}
    if summary.get("phase") != "awaiting_plan_approval":
        raise HTTPException(status_code=409, detail={"code": "PLAN_NOT_AWAITING_APPROVAL", "message": "Run is not waiting for plan approval."})
    job_id = str(row["job_id"])
    context, cleaned_prompt, files, input_assets = load_agent_run_context_for_job(
        user_id=user_id,
        job_id=job_id,
        session_id=jwt_jti or "anonymous",
    )
    plan_preview = summary.get("planPreview") if isinstance(summary.get("planPreview"), dict) else get_plan_preview(user_id, run_id)["planPreview"]

    if normalized == "rejected":
        context.run_log.append(
            stage="plan_rejected",
            status="succeeded",
            input_summary="User rejected the generated plan.",
            output_summary="Create run canceled; run log retained for maintainer review.",
            metrics={"planPreview": plan_preview},
        )
        context.task_state.resume_status = "rejected_by_user"
        context.task_store.checkpoint(
            context.task_state,
            "plan_rejected",
            {"planPreview": plan_preview, "decision": "rejected"},
            context.run_log.object_key,
        )
        if input_assets:
            _cleanup_failed_input_assets(job_id=job_id, user_id=user_id, input_assets=input_assets)
        redis_client().delete(_plan_approval_cache_key(run_id))
        redis_client().delete(f"create:input-assets:{job_id}")
        with db_connection() as connection:
            connection.execute(
                """
UPDATE generation_jobs
SET status = 'canceled', current_stage = 'plan_rejected', completed_at = now()
WHERE id = %s
""",
                (job_id,),
            )
            connection.execute(
                """
UPDATE create_runs
SET status = 'canceled', summary = summary || %s, completed_at = now()
WHERE id = %s
""",
                (Jsonb({"phase": "rejected", "planDecision": "rejected"}), run_id),
            )
            if row["create_type"] == "init":
                connection.execute(
                    """
UPDATE agent_projects
SET status = 'deleted', metadata = metadata || %s, updated_at = now()
WHERE id = %s AND game_id IS NULL
""",
                    (Jsonb({"rejectedRunId": run_id, "rejectedAt": "now"}), row["project_id"]),
                )
        finalize_agent_run(
            context=context,
            status_value="canceled",
            job_id=job_id,
            summary={"phase": "rejected", "planDecision": "rejected", "planPreview": plan_preview},
            final_answer="Plan rejected by user.",
        )
        return get_generation_job(job_id)  # type: ignore[return-value]

    context.run_log.append(
        stage="plan_accepted",
        status="succeeded",
        input_summary="User accepted the generated plan.",
        output_summary="Create generation will continue from the approved plan.",
        metrics={"planPreview": plan_preview},
    )
    context.task_store.checkpoint(
        context.task_state,
        "plan_accepted",
        {"planPreview": plan_preview, "decision": "accepted"},
        context.run_log.object_key,
    )
    with db_connection() as connection:
        connection.execute(
            """
UPDATE create_runs
SET summary = summary || %s
WHERE id = %s
""",
            (Jsonb({"phase": "generating_after_plan_approval", "planDecision": "accepted"}), run_id),
        )
        connection.execute(
            """
UPDATE generation_jobs
SET status = 'generating', current_stage = 'plan_accepted'
WHERE id = %s
""",
            (job_id,),
        )
    redis_client().delete(_plan_approval_cache_key(run_id))
    ai_config = _load_ai_config(user_id, jwt_jti)
    if not ai_config:
        raise HTTPException(status_code=409, detail={"code": "AI_CONFIG_REQUIRED", "message": "AI configuration is required before continuing."})
    try:
        _execute_generation_job_loaded(
            job_id=job_id,
            creator_id=user_id,
            cleaned_prompt=cleaned_prompt,
            files=files,
            input_assets=input_assets,
            ai_config=ai_config,
            context=context,
            approved_plan=plan_preview,
        )
    except Exception as exc:
        _fail_generation_job(
            context=context,
            job_id=job_id,
            code=exc.__class__.__name__,
            message=str(exc) or "Create generation failed.",
            stage="run_failed",
        )
    return get_generation_job(job_id)  # type: ignore[return-value]


def get_decentralized_preview_state(user_id: str, run_id: str) -> dict[str, Any]:
    ensure_create_runtime_schema()
    return get_decentralized_previews(user_id=user_id, run_id=run_id)


def choose_decentralized_candidate(user_id: str, run_id: str, candidate_id: str) -> dict[str, Any]:
    ensure_create_runtime_schema()
    state = select_decentralized_candidate(user_id=user_id, run_id=run_id, candidate_id=candidate_id)
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT job_id
FROM create_runs
WHERE id = %s AND user_id = %s
LIMIT 1
""",
            (run_id, user_id),
        ).fetchone()
    if row and row["job_id"]:
        context, _prompt, _files, _input_assets = load_agent_run_context_for_job(
            user_id=user_id,
            job_id=str(row["job_id"]),
            session_id="selection",
        )
        context.run_log.append(
            stage="decentralized_candidate_selected",
            status="succeeded",
            input_summary="User selected a decentralized static preview candidate.",
            output_summary="Waiting for explicit confirmation before final generation starts.",
            metrics={"selectedCandidateId": candidate_id},
        )
    return state


def decide_decentralized_run(user_id: str, run_id: str, decision: str, jwt_jti: str | None = None) -> CreateJob:
    ensure_create_runtime_schema()
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT r.job_id, r.agent_mode, j.creator_id
FROM create_runs r
JOIN generation_jobs j ON j.id = r.job_id
WHERE r.id = %s AND r.user_id = %s
LIMIT 1
""",
            (run_id, user_id),
        ).fetchone()
    if not row:
        raise HTTPException(status_code=404, detail="Run not found")
    if row["agent_mode"] != "decentralized":
        raise HTTPException(status_code=409, detail={"code": "NOT_DECENTRALIZED_RUN", "message": "Run is not a decentralized run."})
    job_id = str(row["job_id"])
    context, cleaned_prompt, files, input_assets = load_agent_run_context_for_job(
        user_id=user_id,
        job_id=job_id,
        session_id=jwt_jti or "anonymous",
    )
    result = confirm_decentralized_run(
        user_id=user_id,
        run_id=run_id,
        decision=decision,
        context=context,
        job_id=job_id,
    )
    if result == "rejected":
        finalize_agent_run(
            context=context,
            status_value="canceled",
            job_id=job_id,
            summary={"phase": "decentralized_rejected", "decision": "rejected"},
            final_answer="Decentralized preview directions were rejected by the user.",
        )
        return get_generation_job(job_id)  # type: ignore[return-value]
    return get_generation_job(job_id)  # type: ignore[return-value]


def execute_decentralized_final_run(user_id: str, run_id: str, jwt_jti: str | None = None) -> None:
    ensure_create_runtime_schema()
    context = None
    job_id = ""
    try:
        with db_connection() as connection:
            row = connection.execute(
                """
SELECT r.job_id
FROM create_runs r
WHERE r.id = %s AND r.user_id = %s AND r.agent_mode = 'decentralized'
LIMIT 1
""",
                (run_id, user_id),
            ).fetchone()
        if not row or not row["job_id"]:
            raise RuntimeError("Decentralized run job was not found.")
        job_id = str(row["job_id"])
        context, cleaned_prompt, _files, input_assets = load_agent_run_context_for_job(
            user_id=user_id,
            job_id=job_id,
            session_id=jwt_jti or "anonymous",
        )
        ai_config = _load_ai_config(user_id, jwt_jti)
        if not ai_config:
            raise RuntimeError("AI configuration is no longer available for this run.")
        allocation = _allocate_project_game_version(creator_id=user_id, context=context, title_hint=cleaned_prompt[:80] or "decentralized-game")
        game_id = allocation["gameId"]
        game_slug = allocation["gameSlug"]
        version_id = allocation["versionId"]
        context.version_no = allocation["versionNo"]
        context.existing_game = allocation["existingGame"]
        final = build_decentralized_final_result(
            job_id=job_id,
            context=context,
            user_request=cleaned_prompt,
            input_assets=input_assets,
            ai_config=ai_config,
            adapter_factory=_make_graph_adapter,
            game_id=game_id,
            version_id=version_id,
            game_slug="pending",
            previous_project_context=_prepare_opt_workspace_context(context=context, user_id=user_id),
        )
        if context.create_type == "init":
            game_slug = f"{_slugify(final.pipeline.title)}-{game_id[:8]}"
        final.pipeline.source["gameSlug"] = game_slug
        _publish_pipeline_for_existing_job(
            job_id=job_id,
            creator_id=user_id,
            context=context,
            pipeline=final.pipeline,
            game_id=game_id,
            version_id=version_id,
            game_slug=game_slug,
            prompt_template=final.prompt_template,
            strategy_metadata=final.strategy_metadata,
            llm_metrics=final.llm_metrics,
            use_static_generation=False,
            cover_artifact=final.cover_artifact,
        )
        clear_decentralized_cache(run_id)
    except Exception as exc:
        if job_id:
            _fail_generation_job(
                context=context,
                job_id=job_id,
                code=exc.__class__.__name__,
                message=str(exc) or "Decentralized final generation failed.",
                stage="run_failed",
            )


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


def _append_llm_output_parse_step(context: Any, parsed_output: dict[str, Any], graph_result: Any) -> None:
    diagnostics = parsed_output.get("diagnostics") if isinstance(parsed_output.get("diagnostics"), dict) else {}
    warnings = parsed_output.get("normalizationWarnings") if isinstance(parsed_output.get("normalizationWarnings"), list) else []
    if parsed_output.get("fallback"):
        context.run_log.append(
            stage="llm_output_contract_failed",
            status="failed",
            input_summary="LLM output did not match the game package contract.",
            output_summary=str(parsed_output.get("fallbackReason") or "invalid_llm_output")[:500],
            metrics={
                "fallbackReason": parsed_output.get("fallbackReason"),
                "finishReason": getattr(graph_result, "finish_reason", None),
                "diagnostics": diagnostics,
            },
        )
        return
    if warnings:
        context.run_log.append(
            stage="llm_output_normalized",
            status="succeeded",
            input_summary="LLM output was accepted after backend normalization.",
            output_summary=", ".join(str(item) for item in warnings)[:500],
            metrics={
                "normalizationWarnings": warnings,
                "finishReason": getattr(graph_result, "finish_reason", None),
                "diagnostics": diagnostics,
            },
        )


def _parse_generation_output_for_context(context: Any, graph_result: Any) -> dict[str, Any]:
    raw_output = _main_agent_output_value(graph_result)
    parsed_output = parse_main_agent_json_output(_hydrate_output_from_workspace(raw_output, context))
    _append_llm_output_parse_step(context, parsed_output, graph_result)
    return parsed_output


def _unwrap_plan_payload(value: str | dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    warnings: list[str] = []
    if isinstance(value, str):
        text = value.strip()
        fence = re.search(r"```(?:json)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
        if fence:
            text = fence.group(1).strip()
            warnings.append("unwrapped_markdown_json")
        else:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                text = text[start : end + 1]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return {}, ["invalid_plan_json"]
    elif isinstance(value, dict):
        parsed = value
    else:
        return {}, ["invalid_plan_payload"]

    current = parsed
    for _ in range(4):
        if isinstance(current, dict) and current.get("type") == "final" and isinstance(current.get("output"), dict):
            current = current["output"]
            warnings.append("unwrapped_final_output")
            continue
        if isinstance(current, dict) and isinstance(current.get("output"), dict) and not current.get("plan"):
            current = current["output"]
            warnings.append("unwrapped_output")
            continue
        break
    return (current if isinstance(current, dict) else {}), warnings


def _normalize_plan_steps(value: Any, warnings: list[str]) -> list[dict[str, Any]]:
    if not isinstance(value, list) or not value:
        warnings.append("missing_plan_generated_default")
        value = [
            {
                "title": "Core implementation",
                "goal": "Create a playable iframe HTML5 game from the user request.",
                "toolFamily": "workspace.*",
                "expectedOutput": "index.html contains the complete playable game.",
                "acceptanceCheckRefs": ["check-1", "check-2"],
            },
            {
                "title": "Runtime safety",
                "goal": "Keep browser runtime safe and compatible with iframe sandbox.",
                "toolFamily": "none",
                "expectedOutput": "Generated code avoids blocked browser capabilities.",
                "acceptanceCheckRefs": ["check-3"],
            },
            {
                "title": "Play validation",
                "goal": "Expose lifecycle events and basic input behavior for the web player.",
                "toolFamily": "test.*",
                "expectedOutput": "Game sends lifecycle postMessage events and accepts input.",
                "acceptanceCheckRefs": ["check-4"],
            },
        ]
    if all(isinstance(item, str) for item in value):
        warnings.append("plan_string_array_normalized")
    steps_out: list[dict[str, Any]] = []
    for index, item in enumerate(value[:8], start=1):
        if isinstance(item, str):
            step = {
                "id": f"step-{index}",
                "title": item[:80] or f"Step {index}",
                "goal": item[:300] or "Implement the planned game behavior.",
                "toolFamily": "workspace.*",
                "expectedOutput": item[:300] or "Playable game output is updated.",
                "acceptanceCheckRefs": [],
            }
        elif isinstance(item, dict):
            step = {
                "id": str(item.get("id") or f"step-{index}")[:40],
                "title": str(item.get("title") or item.get("step") or f"Step {index}")[:120],
                "goal": str(item.get("goal") or item.get("description") or item.get("step") or "Implement part of the game.")[:500],
                "toolFamily": str(item.get("toolFamily") or item.get("tool_family") or "workspace.*")[:80],
                "expectedOutput": str(item.get("expectedOutput") or item.get("expected_output") or "Playable game behavior is produced.")[:500],
                "acceptanceCheckRefs": item.get("acceptanceCheckRefs") if isinstance(item.get("acceptanceCheckRefs"), list) else [],
            }
        else:
            continue
        if not re.fullmatch(r"step-\d+", step["id"]):
            step["id"] = f"step-{index}"
            warnings.append("invalid_plan_step_id_normalized")
        step["acceptanceCheckRefs"] = [str(ref)[:60] for ref in step["acceptanceCheckRefs"] if isinstance(ref, (str, int))]
        steps_out.append(step)
    if isinstance(value, list) and len(value) > 8:
        warnings.append("plan_steps_truncated_to_8")
    return steps_out or _normalize_plan_steps([], warnings)


def _normalize_acceptance_checks(value: Any, warnings: list[str]) -> list[dict[str, Any]]:
    allowed_types = {"runtime", "safety", "artifact", "ux", "performance"}
    allowed_severity = {"must", "should", "nice"}
    if not isinstance(value, list) or not value:
        warnings.append("missing_acceptance_checks_generated_default")
        value = [
            {"description": "index.html is self-contained and runs inside iframe sandbox.", "type": "artifact", "severity": "must"},
            {"description": "Game loop uses requestAnimationFrame.", "type": "performance", "severity": "must"},
            {"description": "Generated game avoids eval, remote scripts, pointer lock, and local file APIs.", "type": "safety", "severity": "must"},
            {"description": "Game sends game_ready and game_start lifecycle events.", "type": "runtime", "severity": "must"},
        ]
    if all(isinstance(item, str) for item in value):
        warnings.append("acceptance_checks_string_array_normalized")
    checks_out: list[dict[str, Any]] = []
    for index, item in enumerate(value[:12], start=1):
        if isinstance(item, str):
            check = {"id": f"check-{index}", "description": item[:500], "type": "runtime", "severity": "must"}
        elif isinstance(item, dict):
            check_type = str(item.get("type") or "runtime")
            severity = str(item.get("severity") or "must")
            if check_type not in allowed_types:
                check_type = "runtime"
                warnings.append("invalid_acceptance_check_type_normalized")
            if severity not in allowed_severity:
                severity = "must"
                warnings.append("invalid_acceptance_check_severity_normalized")
            check = {
                "id": str(item.get("id") or f"check-{index}")[:40],
                "description": str(item.get("description") or item.get("text") or item.get("message") or "Verify generated game behavior.")[:500],
                "type": check_type,
                "severity": severity,
            }
        else:
            continue
        if not re.fullmatch(r"check-\d+", check["id"]):
            check["id"] = f"check-{index}"
            warnings.append("invalid_acceptance_check_id_normalized")
        checks_out.append(check)
    return checks_out or _normalize_acceptance_checks([], warnings)


def _normalize_risks(value: Any, warnings: list[str]) -> list[str]:
    if not isinstance(value, list) or not value:
        warnings.append("missing_risks_generated_default")
        return [
            "Keyboard or touch input may affect the parent page if default browser behavior is not prevented.",
            "Generated code must avoid blocked browser APIs and remote scripts.",
        ]
    risks: list[str] = []
    for item in value[:12]:
        if isinstance(item, str):
            text = item
        elif isinstance(item, dict):
            text = str(item.get("description") or item.get("message") or item.get("text") or "")
        else:
            text = ""
        text = text.strip()
        if text:
            risks.append(text[:500])
    return risks or _normalize_risks([], warnings)


def normalize_plan_preview_output(value: str | dict[str, Any]) -> dict[str, Any]:
    payload, warnings = _unwrap_plan_payload(value)
    plan = _normalize_plan_steps(payload.get("plan"), warnings)
    checks = _normalize_acceptance_checks(payload.get("acceptanceChecks") or payload.get("acceptance_checks"), warnings)
    valid_check_ids = {check["id"] for check in checks}
    for step in plan:
        original_refs = list(step["acceptanceCheckRefs"])
        step["acceptanceCheckRefs"] = [ref for ref in original_refs if ref in valid_check_ids]
        if original_refs and len(original_refs) != len(step["acceptanceCheckRefs"]):
            warnings.append("invalid_acceptance_check_refs_removed")
    risks = _normalize_risks(payload.get("risks"), warnings)
    return {
        "plan": plan,
        "risks": risks,
        "acceptanceChecks": checks,
        "normalizationWarnings": list(dict.fromkeys(warnings)),
    }


def _settings_with_approved_plan(settings: AgentRequestSettings, plan_preview: dict[str, Any]) -> AgentRequestSettings:
    approved_payload = json.dumps(
        {
            "plan": plan_preview.get("plan", []),
            "risks": plan_preview.get("risks", []),
            "acceptanceChecks": plan_preview.get("acceptanceChecks", []),
        },
        ensure_ascii=False,
    )
    return AgentRequestSettings(
        user_request=settings.user_request,
        create_type=settings.create_type,
        agent_mode=settings.agent_mode,
        workspace_capability=settings.workspace_capability,
        workspace_boundary=settings.workspace_boundary,
        recent_8_history=settings.recent_8_history,
        persistent_memory_summary=[
            *settings.persistent_memory_summary,
            {"memoryType": "approved_plan", "payload": approved_payload},
        ],
        tool_metadata=settings.tool_metadata,
        input_assets=settings.input_assets,
    )


def _hydrate_output_from_workspace(value: str | dict[str, Any], context: Any) -> str | dict[str, Any]:
    def coerce_root(candidate: str | dict[str, Any]) -> str | dict[str, Any]:
        if isinstance(candidate, dict):
            return candidate
        text = candidate.strip()
        start = text.find("{")
        end = text.rfind("}")
        if start >= 0 and end > start:
            text = text[start : end + 1]
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError:
            return candidate
        return parsed if isinstance(parsed, dict) else candidate

    def output_container(root: dict[str, Any]) -> dict[str, Any]:
        if root.get("type") == "final" and isinstance(root.get("output"), dict):
            return root["output"]
        if isinstance(root.get("output"), dict) and not root.get("files"):
            return root["output"]
        return root

    root = coerce_root(value)
    if not isinstance(root, dict):
        return value

    container = output_container(root)
    fs = WorkspaceFS(context.workspace)
    files = container.get("files")
    warnings = container.get("normalizationWarnings") if isinstance(container.get("normalizationWarnings"), list) else []
    hydrated = False

    if isinstance(files, list):
        for entry in files:
            if not isinstance(entry, dict):
                continue
            workspace_path = entry.get("workspacePath") or entry.get("workspace_path")
            content = entry.get("content")
            if not workspace_path and (
                not isinstance(content, str)
                or not content.strip()
                or content.strip().lower().startswith("see workspace file")
            ):
                workspace_path = entry.get("path")
            if not isinstance(workspace_path, str) or not workspace_path:
                continue
            try:
                entry["content"] = fs.read_text(workspace_path)
            except Exception:
                continue
            entry["workspacePath"] = workspace_path
            hydrated = True

    files = container.get("files")
    has_content_index = any(
        isinstance(entry, dict)
        and isinstance(entry.get("content"), str)
        and PurePosixPath(str(entry.get("path", ""))).name == "index.html"
        for entry in files
    ) if isinstance(files, list) else False
    if not has_content_index:
        try:
            index_html = fs.read_text("index.html")
        except Exception:
            index_html = ""
        if index_html.strip():
            if not isinstance(files, list):
                files = []
                container["files"] = files
            files.append({"path": "index.html", "workspacePath": "index.html", "content": index_html})
            warnings.append("collected_index_html_from_workspace")
            hydrated = True

    if hydrated:
        warnings.append("hydrated_workspace_files")
        container["normalizationWarnings"] = list(dict.fromkeys(str(item) for item in warnings))
    return root


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


def _safe_svg_text(value: Any, limit: int = 160) -> str:
    text = str(value or "").strip()[:limit]
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _default_cover_artifact(*, title: str, description: str, reason: str) -> CoverAgentArtifact:
    safe_title = _safe_svg_text(title or "Generated Game", 90)
    safe_description = _safe_svg_text(description or "Playable HTML5 game", 130)
    safe_reason = _safe_svg_text(reason or "cover fallback", 120)
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" width="{COVER_WIDTH}" height="{COVER_HEIGHT}" viewBox="0 0 {COVER_WIDTH} {COVER_HEIGHT}" role="img" aria-label="{safe_title}">
  <defs>
    <linearGradient id="bg" x1="0" y1="0" x2="1" y2="1">
      <stop offset="0" stop-color="#111827"/>
      <stop offset="0.52" stop-color="#164e63"/>
      <stop offset="1" stop-color="#7c2d12"/>
    </linearGradient>
    <pattern id="grid" width="64" height="64" patternUnits="userSpaceOnUse">
      <path d="M64 0H0V64" fill="none" stroke="#ffffff" stroke-opacity="0.09" stroke-width="2"/>
    </pattern>
  </defs>
  <rect width="1200" height="900" fill="url(#bg)"/>
  <rect width="1200" height="900" fill="url(#grid)"/>
  <rect x="80" y="96" width="1040" height="708" rx="36" fill="#020617" fill-opacity="0.52" stroke="#ffffff" stroke-opacity="0.22" stroke-width="3"/>
  <circle cx="930" cy="248" r="108" fill="#facc15" fill-opacity="0.88"/>
  <circle cx="1002" cy="314" r="72" fill="#fb7185" fill-opacity="0.82"/>
  <path d="M146 660 C300 520 380 612 516 476 C660 332 794 414 1054 218" fill="none" stroke="#38bdf8" stroke-width="18" stroke-linecap="round" stroke-opacity="0.9"/>
  <text x="120" y="248" fill="#f8fafc" font-family="Arial, Helvetica, sans-serif" font-size="74" font-weight="800">{safe_title}</text>
  <text x="124" y="326" fill="#cbd5e1" font-family="Arial, Helvetica, sans-serif" font-size="30">{safe_description}</text>
  <text x="124" y="736" fill="#fed7aa" font-family="Arial, Helvetica, sans-serif" font-size="24">Fallback cover generated by Gameweare backend: {safe_reason}</text>
</svg>"""
    content = svg.encode("utf-8")
    return CoverAgentArtifact(
        artifact=AgentArtifact("cover.svg", content, "image/svg+xml", "cover", "fallback"),
        summary=f"Fallback SVG cover generated by backend because {reason}.",
        metrics={"agent": "backend-cover-fallback", "reason": reason, "width": COVER_WIDTH, "height": COVER_HEIGHT},
        raw_kind="fallback_svg",
    )


def _copy_existing_cover_artifact(context: Any) -> CoverAgentArtifact | None:
    existing_game = getattr(context, "existing_game", None)
    cover_asset_id = existing_game.get("cover_asset_id") if isinstance(existing_game, dict) else None
    if not cover_asset_id:
        return None
    with db_connection() as connection:
        asset = connection.execute(
            """
SELECT bucket, object_key, content_type, width, height
FROM assets
WHERE id = %s AND kind = 'cover'
LIMIT 1
""",
            (cover_asset_id,),
        ).fetchone()
    if not asset or not asset["bucket"] or not asset["object_key"]:
        return None
    try:
        response = _minio_client().get_object(asset["bucket"], asset["object_key"])
        try:
            content = response.read()
        finally:
            response.close()
            response.release_conn()
    except Exception:
        return None
    content_type = str(asset["content_type"] or "image/svg+xml").split(";", 1)[0]
    if not content:
        return None
    return CoverAgentArtifact(
        artifact=AgentArtifact(_filename_for_existing_cover(content_type), content, content_type, "cover", "fallback"),
        width=int(asset["width"] or COVER_WIDTH),
        height=int(asset["height"] or COVER_HEIGHT),
        summary="Reused the previous project cover because Cover Agent generation failed.",
        metrics={"agent": "backend-cover-fallback", "fallback": "previous_cover", "sourceAssetId": str(cover_asset_id)},
        raw_kind="reused_previous_cover",
    )


def _filename_for_existing_cover(content_type: str) -> str:
    return f"cover.{_cover_extension_for_content_type(content_type)}"


def _fallback_cover_artifact(*, context: Any, pipeline: Any, reason: str) -> CoverAgentArtifact:
    reused = _copy_existing_cover_artifact(context)
    if reused:
        return reused
    return _default_cover_artifact(title=pipeline.title, description=pipeline.description, reason=reason)


def _degraded_cover_artifact(*, context: Any, pipeline: Any, reason: str, diagnostics: dict[str, Any] | None = None) -> CoverAgentArtifact:
    artifact = _fallback_cover_artifact(context=context, pipeline=pipeline, reason=reason)
    context.run_log.append(
        stage="cover_generation_degraded",
        status="succeeded",
        input_summary="Cover Agent output was unavailable or not publishable.",
        output_summary=artifact.summary,
        metrics={
            "reason": reason,
            "diagnostics": diagnostics or {},
            "fallbackRawKind": artifact.raw_kind,
            "contentType": artifact.content_type,
            "sizeBytes": artifact.size_bytes,
            "width": artifact.width,
            "height": artifact.height,
        },
    )
    return artifact


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
            "required": False,
            "degraded": cover_artifact.raw_kind.startswith("fallback") or cover_artifact.raw_kind == "reused_previous_cover",
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


def _scan_publish_artifacts(artifacts: list[AgentArtifact], entry_file: str) -> dict[str, Any]:
    issues: list[dict[str, str]] = []
    total_bytes = sum(len(artifact.content) for artifact in artifacts)
    max_initial_bytes = 1_500_000
    max_total_bytes = 8_000_000
    if total_bytes > max_total_bytes:
        issues.append({"code": "TOTAL_SIZE_LIMIT", "message": "Generated package exceeds the MVP total size limit."})
    for artifact in artifacts:
        if len(artifact.content) > max_initial_bytes and artifact.filename == entry_file:
            issues.append({"code": "ENTRY_SIZE_LIMIT", "message": "Playable entry file is too large for MVP iframe loading."})
        if artifact.content_type.split(";", 1)[0] != "text/html" and not artifact.filename.endswith(".html"):
            continue
        html = artifact.content.decode("utf-8", errors="ignore").lower()
        parser = PublishHtmlSafetyParser(artifact.filename)
        try:
            parser.feed(artifact.content.decode("utf-8", errors="ignore"))
            parser.close()
            issues.extend(parser.issues)
        except Exception:
            issues.append({"code": "HTML_PARSE_FAILED", "message": f"{artifact.filename} could not be parsed for safety scanning."})
        checks = {
            "POINTER_LOCK_BLOCKED": "requestpointerlock",
            "TOP_ACCESS_BLOCKED": "top.location",
            "EVAL_BLOCKED": "eval(",
            "FUNCTION_CONSTRUCTOR_BLOCKED": "new function",
            "LOCAL_STORAGE_BLOCKED": "localstorage",
            "SESSION_STORAGE_BLOCKED": "sessionstorage",
            "INDEXED_DB_BLOCKED": "indexeddb",
            "COOKIE_ACCESS_BLOCKED": "document.cookie",
            "NETWORK_FETCH_BLOCKED": "fetch(",
            "XHR_BLOCKED": "xmlhttprequest",
            "WEBSOCKET_BLOCKED": "websocket(",
            "DYNAMIC_IMPORT_BLOCKED": "import(",
            "WORKER_BLOCKED": "new worker",
        }
        for code, needle in checks.items():
            if needle in html:
                issues.append({"code": code, "message": f"{artifact.filename} contains blocked browser capability: {needle}"})
        if _html_has_blocked_parent_access(html):
            issues.append({"code": "PARENT_ACCESS_BLOCKED", "message": f"{artifact.filename} accesses window.parent outside postMessage."})
        if "<script" in html and "src=\"http" in html:
            issues.append({"code": "REMOTE_SCRIPT_BLOCKED", "message": f"{artifact.filename} references a remote script."})
        if artifact.filename == entry_file:
            if "<html" not in html or "<script" not in html:
                issues.append({"code": "ENTRY_HTML_INVALID", "message": "Playable entry file must be a complete HTML document with script."})
            if "see workspace file:" in html:
                issues.append({"code": "ENTRY_WORKSPACE_PLACEHOLDER", "message": "Playable entry file is a workspace reference placeholder, not game HTML."})
    return {
        "passed": not issues,
        "issues": issues,
        "artifactCount": len(artifacts),
        "totalBytes": total_bytes,
        "limits": {"maxInitialBytes": max_initial_bytes, "maxTotalBytes": max_total_bytes},
    }


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
    try:
        result = _make_graph_adapter(ai_config).invoke(prompt_payload)
    except Exception as exc:
        return _degraded_cover_artifact(
            context=context,
            pipeline=pipeline,
            reason="cover_provider_exception",
            diagnostics={"error": exc.__class__.__name__, "message": str(exc)[:500]},
        )
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
    cover_provider_error = provider_error_diagnostics(result.raw if isinstance(result.raw, dict) else None)
    context.run_log.append(
        stage="cover_llm_call",
        status="failed" if cover_provider_error else "succeeded",
        input_summary=str(result.metrics.get("promptPrefix") or "")[:500],
        output_summary=(
            str(cover_provider_error.get("message") or cover_provider_error.get("code"))[:500]
            if cover_provider_error
            else ("Cover model response received." if result.text or result.raw else "Cover model returned an empty response.")
        ),
        metrics={**_safe_cover_llm_metrics(result.metrics), "providerError": cover_provider_error},
    )
    if cover_provider_error:
        return _degraded_cover_artifact(
            context=context,
            pipeline=pipeline,
            reason="cover_provider_error",
            diagnostics={"providerError": cover_provider_error},
        )
    try:
        cover_artifact = parse_cover_agent_output(result)
    except Exception as exc:
        return _degraded_cover_artifact(
            context=context,
            pipeline=pipeline,
            reason="cover_output_contract_failed",
            diagnostics={
                "error": exc.__class__.__name__,
                "message": str(exc)[:500],
                "outputChars": len(result.text or ""),
            },
        )
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


def _cache_recent_published_game_for_job(connection: Connection, *, user_id: str, job_id: str) -> RecentGame | None:
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
  gj.id = %s
  AND gj.creator_id = %s
  AND g.publish_status = 'published'
  AND g.visibility = 'public'
  AND g.deleted_at IS NULL
LIMIT 1
""",
        (job_id, user_id),
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


def publish_generation_job(user_id: str, job_id: str) -> CreateJob:
    ensure_create_runtime_schema()
    with db_connection() as connection:
        row = connection.execute(
            """
SELECT gj.id, gj.status, gj.game_id, gj.version_id, g.author_id, g.publish_status
FROM generation_jobs gj
JOIN games g ON g.id = gj.game_id
WHERE gj.id = %s AND gj.creator_id = %s AND g.deleted_at IS NULL
LIMIT 1
""",
            (job_id, user_id),
        ).fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="Job not found")
        if row["status"] != "completed" or not row["game_id"] or not row["version_id"]:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "JOB_NOT_READY", "message": "Only completed generated drafts can be published."},
            )
        connection.execute(
            """
UPDATE games
SET
  visibility = 'public',
  publish_status = 'published',
  current_version_id = %s,
  published_at = COALESCE(published_at, now()),
  updated_at = now()
WHERE id = %s AND author_id = %s
""",
            (row["version_id"], row["game_id"], user_id),
        )
        _prune_old_game_versions(connection, game_id=str(row["game_id"]), keep=2)
        connection.execute("UPDATE generation_jobs SET current_stage = 'published', updated_at = now() WHERE id = %s", (job_id,))
        connection.execute(
            """
UPDATE agent_projects
SET metadata = metadata || %s, updated_at = now()
WHERE user_id = %s AND game_id = %s
""",
            (Jsonb({"publishStatus": "published", "publishedJobId": job_id}), user_id, row["game_id"]),
        )
        _cache_recent_published_game_for_job(connection, user_id=user_id, job_id=job_id)
    return get_generation_job(job_id)  # type: ignore[return-value]


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


def _normalize_requested_agent_mode(*, create_type: str, agent_mode: str) -> str:
    normalized_create_type = (create_type or "init").strip().lower()
    normalized_mode = (agent_mode or "chat").strip().lower()
    init_modes = {"chat", "react", "plan", "decentralized"}
    opt_modes = {"chat", "react", "plan", "decentralized", "refine"}
    if normalized_create_type == "init":
        if normalized_mode not in init_modes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_AGENT_MODE_FOR_INIT",
                    "message": "Initial creation supports chat, react, plan, and decentralized modes.",
                    "allowedAgentModes": sorted(init_modes),
                },
            )
        return normalized_mode
    if normalized_create_type == "opt":
        if normalized_mode == "opt":
            normalized_mode = "refine"
        if normalized_mode not in opt_modes:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail={
                    "code": "INVALID_AGENT_MODE_FOR_OPT",
                    "message": "Continue optimization supports chat, react, plan, decentralized, and refine modes.",
                    "allowedAgentModes": sorted(opt_modes),
                },
            )
        return normalized_mode
    return normalized_mode


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
    agent_mode = _normalize_requested_agent_mode(create_type=create_type, agent_mode=agent_mode)
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
        if context.agent_mode == "decentralized":
            refinement_memory = _prepare_opt_workspace_context(context=context, user_id=creator_id)
            generate_decentralized_previews(
                job_id=job_id,
                context=context,
                user_request=cleaned_prompt,
                input_assets=input_assets,
                ai_config=ai_config,
                adapter_factory=_make_graph_adapter,
                previous_project_context=refinement_memory,
            )
            return
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
        failure_metrics = exc.diagnostics if isinstance(exc, CreateLLMGenerationError) else {}
        _fail_generation_job(
            context=context,
            job_id=job_id,
            code="MULTIMODAL_UNSUPPORTED" if isinstance(exc, MultimodalUnsupportedError) else exc.__class__.__name__,
            message=str(exc) or "Create generation failed.",
            stage="run_failed",
            metrics=failure_metrics,
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
    approved_plan: dict[str, Any] | None = None,
) -> None:
    _update_job_stage(job_id, "planning", "prompt_render")
    tool_metadata = list_builtin_tool_metadata()
    refinement_memory = _prepare_opt_workspace_context(context=context, user_id=creator_id)
    prompt_settings = AgentRequestSettings.from_create_context(
        user_request=cleaned_prompt,
        create_type=context.create_type,
        agent_mode=context.agent_mode,
        recent_8_history=context.long_term_memory.snapshot().get("history", []),
        workspace_capability=context.workspace.capability,
        workspace_boundary=context.workspace.worktree_stub_path,
        persistent_memory_summary=[
            *refinement_memory,
            *context.persistent_memory.list(
                user_id=creator_id,
                project_id=context.project_id,
            ),
        ],
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
    multi_agent_contracts = record_multi_agent_contracts(context, agent_mode=context.agent_mode)
    if multi_agent_contracts:
        strategy_metadata = {**strategy_metadata, "multiAgentContracts": multi_agent_contracts}
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

    if context.agent_mode == "plan" and approved_plan is None:
        _execute_plan_preview(
            job_id=job_id,
            context=context,
            prompt_settings=prompt_settings,
            strategy=strategy,
            ai_config=ai_config,
            prompt_template=prompt_template,
            strategy_metadata=strategy_metadata,
        )
        return
    if context.agent_mode == "plan" and approved_plan is not None:
        prompt_settings = _settings_with_approved_plan(prompt_settings, approved_plan)

    use_static_generation = get_settings().create_static_generation
    cover_artifact: CoverAgentArtifact | None = None
    allocation = _allocate_project_game_version(creator_id=creator_id, context=context, title_hint=cleaned_prompt[:80] or "generated-game")
    game_id = allocation["gameId"]
    game_slug = allocation["gameSlug"]
    version_id = allocation["versionId"]
    context.version_no = allocation["versionNo"]
    context.existing_game = allocation["existingGame"]
    _update_job_stage(job_id, "generating", "static_generation" if use_static_generation else "llm_generation")
    context.run_log.append(
        stage="static_generation_started" if use_static_generation else "llm_generation_started",
        status="running",
        input_summary=("Static generation pipeline is starting." if use_static_generation else "LangGraph LLM generation is starting."),
        output_summary="Game and version identifiers allocated.",
        metrics={"gameId": game_id, "versionId": version_id, "versionNo": context.version_no, "staticGeneration": use_static_generation},
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
        if context.create_type == "init":
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
        try:
            graph_result = strategy.run_langgraph(
                settings=prompt_settings,
                model=ai_config["model"],
                adapter=_make_graph_adapter(ai_config),
                registry=build_builtin_tool_registry(context.workspace),
                recorder=recorder,
            )
        except LLMProviderCallError as exc:
            diagnostics = exc.diagnostics
            raw = {"ok": False, "error": diagnostics}
            if input_assets and _is_multimodal_unsupported_error(raw):
                _cleanup_failed_input_assets(job_id=job_id, user_id=creator_id, input_assets=input_assets)
                raise MultimodalUnsupportedError(
                    "MULTIMODAL_UNSUPPORTED: The configured API/model rejected image input. "
                    "Please switch to a vision-capable OpenAI Responses-compatible model or create without images."
                )
            context.run_log.append(
                stage="llm_generation_failed",
                status="failed",
                input_summary="LLM provider call failed during LangGraph generation.",
                output_summary=str(diagnostics.get("message") or diagnostics.get("code") or "Provider call failed.")[:500],
                metrics={"providerError": diagnostics, "strategy": strategy_metadata.get("strategy")},
            )
            raise CreateLLMGenerationError("The LLM provider call failed during generation.", {"providerError": diagnostics}) from exc
        provider_error = _latest_provider_error(graph_result.messages)
        if provider_error:
            context.run_log.append(
                stage="llm_generation_failed",
                status="failed",
                input_summary="LLM provider call failed during LangGraph generation.",
                output_summary=str(provider_error.get("message") or provider_error.get("code") or "Provider call failed.")[:500],
                metrics={"providerError": provider_error, "strategy": strategy_metadata.get("strategy")},
            )
            raise CreateLLMGenerationError("The LLM provider call failed during generation.", {"providerError": provider_error})
        last_message = graph_result.messages[-1] if graph_result.messages else {}
        llm_metrics = last_message.get("metrics") if isinstance(last_message.get("metrics"), dict) else {}
        parsed_output = _parse_generation_output_for_context(context, graph_result)
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
        if context.create_type == "init":
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


def _execute_plan_preview(
    *,
    job_id: str,
    context: Any,
    prompt_settings: AgentRequestSettings,
    strategy: Any,
    ai_config: dict[str, str],
    prompt_template: dict[str, Any],
    strategy_metadata: dict[str, Any],
) -> None:
    _update_job_stage(job_id, "planning", "plan_approval")
    context.run_log.append(
        stage="plan_generation_started",
        status="running",
        input_summary="Plan strategy is generating a user-reviewable plan.",
        output_summary="No game artifacts will be published until the user accepts the plan.",
        metrics={"jobId": job_id, "strategy": strategy_metadata},
    )
    recorder = LLMCallRecorder(
        long_term_memory=context.long_term_memory,
        short_term_memory=context.short_term_memory,
        run_log=context.run_log,
    )
    try:
        graph_result = strategy.run_langgraph(
            settings=prompt_settings,
            model=ai_config["model"],
            adapter=_make_graph_adapter(ai_config),
            registry=build_builtin_tool_registry(context.workspace),
            recorder=recorder,
        )
    except LLMProviderCallError as exc:
        diagnostics = exc.diagnostics
        raw = {"ok": False, "error": diagnostics}
        if _is_multimodal_unsupported_error(raw):
            raise MultimodalUnsupportedError(
                "MULTIMODAL_UNSUPPORTED: The configured API/model rejected image input. "
                "Please switch to a vision-capable OpenAI Responses-compatible model or create without images."
            ) from exc
        context.run_log.append(
            stage="plan_generation_failed",
            status="failed",
            input_summary="LLM provider call failed during plan preview generation.",
            output_summary=str(diagnostics.get("message") or diagnostics.get("code") or "Provider call failed.")[:500],
            metrics={"providerError": diagnostics},
        )
        raise CreateLLMGenerationError("The LLM provider call failed during plan generation.", {"providerError": diagnostics}) from exc
    provider_error = _latest_provider_error(graph_result.messages)
    if provider_error:
        context.run_log.append(
            stage="plan_generation_failed",
            status="failed",
            input_summary="LLM provider call failed during plan preview generation.",
            output_summary=str(provider_error.get("message") or provider_error.get("code") or "Provider call failed.")[:500],
            metrics={"providerError": provider_error},
        )
        raise CreateLLMGenerationError("The LLM provider call failed during plan generation.", {"providerError": provider_error})
    plan_preview = normalize_plan_preview_output(_main_agent_output_value(graph_result))
    context.run_log.append(
        stage="plan_ready",
        status="succeeded",
        input_summary="Plan preview generated for user approval.",
        output_summary=f"{len(plan_preview['plan'])} steps, {len(plan_preview['acceptanceChecks'])} checks, {len(plan_preview['risks'])} risks.",
        metrics={
            "planPreview": plan_preview,
            "normalizationWarnings": plan_preview.get("normalizationWarnings", []),
        },
    )
    context.task_store.checkpoint(
        context.task_state,
        "plan_waiting_for_approval",
        {
            "promptTemplate": prompt_template,
            "agentStrategy": strategy_metadata,
            "planPreview": plan_preview,
        },
        context.run_log.object_key,
    )
    summary = {
        "phase": "awaiting_plan_approval",
        "planPreview": plan_preview,
        "promptTemplate": prompt_template,
        "agentStrategy": strategy_metadata,
    }
    redis_client().setex(
        _plan_approval_cache_key(context.run_id),
        PLAN_APPROVAL_TTL_SECONDS,
        json.dumps({"jobId": job_id, "planPreview": plan_preview}, ensure_ascii=False, default=str),
    )
    with db_connection() as connection:
        connection.execute("UPDATE create_runs SET summary = %s WHERE id = %s", (Jsonb(summary), context.run_id))
        connection.execute(
            """
UPDATE generation_jobs
SET status = 'planning', current_stage = 'plan_approval'
WHERE id = %s
""",
            (job_id,),
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
    version_no = int(getattr(context, "version_no", 1) or 1)
    existing_game = getattr(context, "existing_game", None)
    publish_artifacts = _publish_artifacts(
        pipeline=pipeline,
        cover_artifact=cover_artifact,
        use_static_generation=use_static_generation,
    )
    safety_scan = _scan_publish_artifacts(publish_artifacts, pipeline.entry_file)
    context.run_log.append(
        stage="safety_scan",
        status="succeeded" if safety_scan["passed"] else "failed",
        input_summary="Generated HTML package scanned before publish.",
        output_summary="No blocked browser capabilities found." if safety_scan["passed"] else "Blocked browser capabilities or resource limits found.",
        metrics=safety_scan,
    )
    if not safety_scan["passed"]:
        raise RuntimeError(f"Generated package failed safety scan: {safety_scan['issues']}")
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
    storage_prefix = f"games/{game_id}/versions/{version_no}"
    api_base = f"http://localhost:{get_settings().api_port}"
    document_url = f"{api_base}/play/{game_slug}/document"
    manifest = {
        "id": game_slug,
        "gameId": game_id,
        "versionId": version_id,
        "version": str(version_no),
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
        if existing_game:
            game = connection.execute(
                """
UPDATE games
SET
  title = %s,
  description = %s,
  metadata = metadata || %s,
  updated_at = now()
WHERE id = %s AND author_id = %s
RETURNING id, slug, title
""",
                (
                    pipeline.title,
                    pipeline.description,
                    Jsonb({"section": "Recently Created", "createdBy": "static-create" if use_static_generation else "llm-create", "agentMode": agent_mode}),
                    game_id,
                    creator_id,
                ),
            ).fetchone()
        else:
            game = connection.execute(
                """
INSERT INTO games (
  id, slug, author_id, title, description, visibility, publish_status, metadata, published_at
)
VALUES (%s, %s, %s, %s, %s, 'private', 'draft', %s, NULL)
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
        previous_version_metadata = {}
        if existing_game and existing_game.get("current_version_id"):
            previous_version = connection.execute(
                "SELECT metadata FROM game_versions WHERE id = %s LIMIT 1",
                (existing_game["current_version_id"],),
            ).fetchone()
            if previous_version and isinstance(previous_version["metadata"], dict):
                previous_version_metadata = previous_version["metadata"]
        version_metadata = {
            **previous_version_metadata,
            "stubbed": use_static_generation,
            "agentMode": agent_mode,
            "llmMetrics": llm_metrics,
            "safetyScan": safety_scan,
            "derivedFromVersionId": str(existing_game["current_version_id"]) if existing_game and existing_game.get("current_version_id") else None,
        }
        version = connection.execute(
            """
INSERT INTO game_versions (
  id, game_id, version_no, source_job_id, runtime, entry_file, build_status, safety_status, storage_prefix, metadata
)
VALUES (%s, %s, %s, %s, %s, %s, 'succeeded', 'passed', %s, %s)
RETURNING id
""",
            (
                version_id,
                game_id,
                version_no,
                job_id,
                pipeline.runtime,
                pipeline.entry_file,
                storage_prefix,
                Jsonb(version_metadata),
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
        _prune_old_game_versions(connection, game_id=game_id, keep=2)
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
            "Game draft is saved. Creator can publish or continue optimizing.",
            {"stubbed": use_static_generation, "agentMode": agent_mode, "bundleUrl": bundle_public_url, "manifestUrl": manifest_public_url},
        )

    context.run_log.append(
        stage="sql_persisted",
        status="succeeded",
        input_summary="Generated game metadata persisted to PostgreSQL.",
        output_summary="Job, game, version, assets, artifacts, and legacy agent logs are linked.",
        metrics={"jobId": job_id, "gameSlug": game_slug, "assetCount": len(artifact_asset_ids) + 1},
    )
    summary = {
        "title": game["title"],
        "gameSlug": game_slug,
        "playUrl": f"/play/{game_slug}",
        "manifestUrl": f"/play/{game_slug}/manifest",
        "publishStatus": "draft",
        "versionNo": version_no,
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
        tags=["draft", agent_mode],
        summary="Generated game draft was saved.",
        payload=summary,
    )
    context.long_term_memory.append_history("assistant", f"Created game draft {game['title']} for project {context.project_id}.")
    context.short_term_memory.record_test({"name": "create_generation", "status": "succeeded"})
    context.run_log.append(
        stage="run_completed",
        status="succeeded",
        input_summary="Create run completed.",
        output_summary="Playable draft is saved and waiting for publish or continue optimize.",
        metrics=summary,
    )
    finalize_agent_run(
        context=context,
        status_value="completed",
        job_id=job_id,
        game_id=game_id,
        version_id=version_id,
        summary=summary,
        final_answer=f"Game draft {game['title']} is ready for review.",
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
    refinement_memory = _prepare_opt_workspace_context(context=context, user_id=creator_id)
    prompt_settings = AgentRequestSettings.from_create_context(
        user_request=cleaned_prompt,
        create_type=context.create_type,
        agent_mode=agent_mode,
        recent_8_history=context.long_term_memory.snapshot().get("history", []),
        workspace_capability=context.workspace.capability,
        workspace_boundary=context.workspace.worktree_stub_path,
        persistent_memory_summary=[
            *refinement_memory,
            *context.persistent_memory.list(
                user_id=creator_id,
                project_id=context.project_id,
            ),
        ],
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
    multi_agent_contracts = record_multi_agent_contracts(context, agent_mode=context.agent_mode)
    if multi_agent_contracts:
        strategy_metadata = {**strategy_metadata, "multiAgentContracts": multi_agent_contracts}
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
    allocation = _allocate_project_game_version(creator_id=creator_id, context=context, title_hint=cleaned_prompt[:80] or "generated-game")
    game_id = allocation["gameId"]
    game_slug = allocation["gameSlug"]
    version_id = allocation["versionId"]
    version_no = int(allocation["versionNo"])
    existing_game = allocation["existingGame"]
    context.version_no = version_no
    context.existing_game = existing_game
    use_static_generation = get_settings().create_static_generation
    generation_stage = "static_generation_started" if use_static_generation else "llm_generation_started"
    context.run_log.append(
        stage=generation_stage,
        status="running",
        input_summary=("Static generation pipeline is starting." if use_static_generation else "LangGraph LLM generation is starting."),
        output_summary="Game and version identifiers allocated.",
        metrics={"gameId": game_id, "versionId": version_id, "versionNo": version_no, "staticGeneration": use_static_generation},
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
        if context.create_type == "init":
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
        try:
            graph_result = strategy.run_langgraph(
                settings=prompt_settings,
                model=ai_config["model"],
                adapter=_make_graph_adapter(ai_config),
                registry=build_builtin_tool_registry(context.workspace),
                recorder=recorder,
            )
        except LLMProviderCallError as exc:
            diagnostics = exc.diagnostics
            context.run_log.append(
                stage="llm_generation_failed",
                status="failed",
                input_summary="LLM provider call failed during LangGraph generation.",
                output_summary=str(diagnostics.get("message") or diagnostics.get("code") or "Provider call failed.")[:500],
                metrics={"providerError": diagnostics},
            )
            finalize_agent_run(
                context=context,
                status_value="failed",
                summary={"error": diagnostics, "stage": "llm_generation_failed"},
                final_answer="LLM generation failed before a playable game could be produced.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LLM_GENERATION_FAILED",
                    "message": "The LLM provider call failed during generation.",
                    "llm": diagnostics,
                },
            ) from exc
        provider_error = _latest_provider_error(graph_result.messages)
        if provider_error:
            context.run_log.append(
                stage="llm_generation_failed",
                status="failed",
                input_summary="LLM provider call failed during LangGraph generation.",
                output_summary=str(provider_error.get("message") or provider_error.get("code") or "Provider call failed.")[:500],
                metrics={"providerError": provider_error},
            )
            finalize_agent_run(
                context=context,
                status_value="failed",
                summary={"error": provider_error, "stage": "llm_generation_failed"},
                final_answer="LLM generation failed before a playable game could be produced.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LLM_GENERATION_FAILED",
                    "message": "The LLM provider call failed during generation.",
                    "llm": provider_error,
                },
            )
        last_message = graph_result.messages[-1] if graph_result.messages else {}
        llm_metrics = last_message.get("metrics") if isinstance(last_message.get("metrics"), dict) else {}
        parsed_output = _parse_generation_output_for_context(context, graph_result)
        if parsed_output.get("fallback"):
            reason = str(parsed_output.get("fallbackReason") or "invalid_llm_output")
            context.run_log.append(
                stage="llm_generation_failed",
                status="failed",
                input_summary="LLM output did not match the game package contract.",
                output_summary=reason[:500],
                metrics={"fallbackReason": reason, "finishReason": graph_result.finish_reason},
            )
            finalize_agent_run(
                context=context,
                status_value="failed",
                summary={"error": reason, "stage": "llm_output_contract_failed"},
                final_answer="LLM generation failed before a playable game could be produced.",
            )
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail={
                    "code": "LLM_OUTPUT_CONTRACT_FAILED",
                    "message": "LLM output did not match the required game package contract.",
                    "reason": reason,
                },
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
        if context.create_type == "init":
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
    safety_scan = _scan_publish_artifacts(pipeline.artifacts, pipeline.entry_file)
    context.run_log.append(
        stage="safety_scan",
        status="succeeded" if safety_scan["passed"] else "failed",
        input_summary="Generated HTML package scanned before publish.",
        output_summary="No blocked browser capabilities found." if safety_scan["passed"] else "Blocked browser capabilities or resource limits found.",
        metrics=safety_scan,
    )
    if not safety_scan["passed"]:
        raise RuntimeError(f"Generated package failed safety scan: {safety_scan['issues']}")
    storage_prefix = f"games/{game_id}/versions/{version_no}"
    api_base = f"http://localhost:{get_settings().api_port}"
    document_url = f"{api_base}/play/{game_slug}/document"

    manifest = {
        "id": game_slug,
        "gameId": game_id,
        "versionId": version_id,
        "version": str(version_no),
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

        if existing_game:
            game = connection.execute(
                """
UPDATE games
SET title = %s, description = %s, metadata = metadata || %s, updated_at = now()
WHERE id = %s AND author_id = %s
RETURNING id, slug, title
""",
                (
                    pipeline.title,
                    pipeline.description,
                    Jsonb({"section": "Recently Created", "createdBy": "static-create" if use_static_generation else "llm-create", "agentMode": agent_mode}),
                    game_id,
                    creator_id,
                ),
            ).fetchone()
        else:
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
VALUES (%s, %s, %s, %s, %s, 'private', 'draft', %s, NULL)
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
VALUES (%s, %s, %s, %s, %s, %s, 'succeeded', 'passed', %s, %s)
RETURNING id
""",
            (
                version_id,
                game_id,
                version_no,
                job_id,
                pipeline.runtime,
                pipeline.entry_file,
                storage_prefix,
                Jsonb(version_metadata),
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
        _prune_old_game_versions(connection, game_id=game_id, keep=2)
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
                "Game draft is saved. Creator can publish or continue optimizing.",
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
SELECT
  gj.id,
  gj.status,
  gj.current_stage,
  gj.prompt,
  gj.input_payload,
  gj.created_at,
  gj.game_id,
  gj.version_id,
  g.slug AS game_slug,
  g.publish_status,
  g.visibility,
  g.deleted_at,
  g.current_version_id,
  gv.version_no
FROM generation_jobs gj
LEFT JOIN games g ON g.id = gj.game_id
LEFT JOIN game_versions gv ON gv.id = gj.version_id
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
    summary = {
        "title": game["title"],
        "gameSlug": game_slug,
        "playUrl": f"/play/{game_slug}",
        "manifestUrl": f"/play/{game_slug}/manifest",
        "publishStatus": "draft",
        "versionNo": version_no,
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
        tags=["draft", agent_mode],
        summary="Generated game draft was saved.",
        payload=summary,
    )
    context.long_term_memory.append_history("assistant", f"Created game draft {game['title']} for project {context.project_id}.")
    context.short_term_memory.record_test({"name": "static_generation_smoke", "status": "succeeded"})
    context.run_log.append(
        stage="run_completed",
        status="succeeded",
        input_summary="Create run completed.",
        output_summary="Playable draft is saved and waiting for publish or continue optimize.",
        metrics=summary,
    )
    finalize_agent_run(
        context=context,
        status_value="completed",
        job_id=job_id,
        game_id=game_id,
        version_id=version_id,
        summary=summary,
        final_answer=f"Game draft {game['title']} is ready for review.",
    )
    return _job_from_row(completed, logs)

def get_generation_job(job_id: str) -> CreateJob | None:
    with db_connection() as connection:
        job = connection.execute(
            """
SELECT
  gj.id,
  gj.status,
  gj.current_stage,
  gj.prompt,
  gj.input_payload,
  gj.created_at,
  gj.game_id,
  gj.version_id,
  g.slug AS game_slug,
  g.publish_status,
  g.visibility,
  g.deleted_at,
  gv.version_no
FROM generation_jobs gj
LEFT JOIN games g ON g.id = gj.game_id
LEFT JOIN game_versions gv ON gv.id = gj.version_id
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
  AND g.publish_status = 'published'
  AND g.visibility = 'public'
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

