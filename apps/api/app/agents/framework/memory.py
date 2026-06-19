from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

from psycopg.types.json import Jsonb

from app.config import get_settings
from app.database import db_connection
from app.services.auth_service import redis_client
from app.agents.framework.storage import put_json_object

LONG_TERM_TTL_SECONDS = 604800
SHORT_TERM_TTL_SECONDS = 86400
HISTORY_LIMIT = 8


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistentMemory:
    def put(
        self,
        *,
        user_id: str,
        project_id: str,
        memory_type: str,
        payload: dict[str, Any],
        tags: list[str] | None = None,
        summary: str | None = None,
    ) -> dict[str, Any]:
        memory_id = str(uuid4())
        object_key = f"agent-memory/{user_id}/{project_id}/{memory_id}.json"
        document = {
            "memoryId": memory_id,
            "userId": user_id,
            "projectId": project_id,
            "memoryType": memory_type,
            "tags": tags or [],
            "summary": summary,
            "payload": payload,
            "createdAt": _now_iso(),
        }
        _, _, digest = put_json_object(object_key, document)
        with db_connection() as connection:
            row = connection.execute(
                """
INSERT INTO agent_memory_index (user_id, project_id, memory_type, tags, bucket, object_key, sha256, summary)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
RETURNING id, object_key, sha256, created_at
""",
                (
                    user_id,
                    project_id,
                    memory_type,
                    tags or [],
                    get_settings().minio_bucket,
                    object_key,
                    digest,
                    summary,
                ),
            ).fetchone()
        return {
            "id": str(row["id"]),
            "objectKey": row["object_key"],
            "sha256": row["sha256"],
            "createdAt": row["created_at"],
        }

    def list(self, *, user_id: str, project_id: str, memory_type: str | None = None) -> list[dict[str, Any]]:
        query = """
SELECT id, memory_type, tags, object_key, sha256, summary, created_at
FROM agent_memory_index
WHERE user_id = %s AND project_id = %s
"""
        params: list[Any] = [user_id, project_id]
        if memory_type:
            query += " AND memory_type = %s"
            params.append(memory_type)
        query += " ORDER BY created_at DESC LIMIT 100"
        with db_connection() as connection:
            rows = connection.execute(query, params).fetchall()
        return [
            {
                "id": str(row["id"]),
                "memoryType": row["memory_type"],
                "tags": row["tags"],
                "objectKey": row["object_key"],
                "sha256": row["sha256"],
                "summary": row["summary"],
                "createdAt": row["created_at"],
            }
            for row in rows
        ]


class LongTermMemory:
    def __init__(self, session_id: str, project_id: str):
        self.session_id = session_id
        self.project_id = project_id

    def _files_key(self) -> str:
        return f"agent:long:{self.session_id}:{self.project_id}:files"

    def _history_key(self) -> str:
        return f"agent:long:{self.session_id}:{self.project_id}:history"

    def record_file_access(
        self,
        *,
        relative_path: str,
        sha256: str,
        size_bytes: int,
        first_500_words: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        payload = {
            "relativePath": relative_path,
            "sha256": sha256,
            "sizeBytes": size_bytes,
            "first500Words": first_500_words,
            "metadata": metadata or {},
            "updatedAt": _now_iso(),
        }
        client = redis_client()
        client.hset(self._files_key(), relative_path, json.dumps(payload, ensure_ascii=False))
        client.expire(self._files_key(), LONG_TERM_TTL_SECONDS)

    def append_history(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        payload = json.dumps(
            {"role": role, "content": content, "metadata": metadata or {}, "createdAt": _now_iso()},
            ensure_ascii=False,
        )
        client = redis_client()
        key = self._history_key()
        client.rpush(key, payload)
        client.ltrim(key, -HISTORY_LIMIT, -1)
        client.expire(key, LONG_TERM_TTL_SECONDS)

    def snapshot(self) -> dict[str, Any]:
        client = redis_client()
        files = [
            json.loads(value)
            for value in client.hvals(self._files_key())
        ]
        history = [
            json.loads(value)
            for value in client.lrange(self._history_key(), 0, -1)
        ]
        return {"files": files, "history": history}


class ShortTermMemory:
    def __init__(self, run_id: str):
        self.run_id = run_id

    def _key(self, category: str) -> str:
        return f"agent:short:{self.run_id}:{category}"

    def record(self, category: str, payload: dict[str, Any]) -> None:
        client = redis_client()
        key = self._key(category)
        client.rpush(key, json.dumps({**payload, "createdAt": _now_iso()}, ensure_ascii=False))
        client.expire(key, SHORT_TERM_TTL_SECONDS)

    def record_tool_call(self, payload: dict[str, Any]) -> None:
        self.record("tool-calls", payload)

    def record_llm_call(self, payload: dict[str, Any]) -> None:
        self.record("llm-calls", payload)

    def record_test(self, payload: dict[str, Any]) -> None:
        self.record("tests", payload)

    def record_file_edit(self, payload: dict[str, Any]) -> None:
        self.record("file-edits", payload)

    def snapshot(self) -> dict[str, list[dict[str, Any]]]:
        client = redis_client()
        result: dict[str, list[dict[str, Any]]] = {}
        for category in ("tool-calls", "tests", "file-edits", "llm-calls"):
            result[category] = [json.loads(value) for value in client.lrange(self._key(category), 0, -1)]
        return result
