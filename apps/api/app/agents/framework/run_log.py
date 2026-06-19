from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from threading import Lock
from typing import Any

from psycopg.types.json import Jsonb

from app.database import db_connection
from app.agents.framework.events import publish_run_event, sanitize_step_event
from app.agents.framework.storage import put_jsonl_object


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class RunLog:
    run_id: str
    records: list[dict[str, Any]] = field(default_factory=list)
    step_no: int = 0
    _lock: Lock = field(default_factory=Lock, init=False, repr=False)

    @property
    def object_key(self) -> str:
        return f"agent-runs/{self.run_id}/run-log.jsonl"

    def append(
        self,
        *,
        stage: str,
        status: str,
        input_summary: str = "",
        output_summary: str = "",
        metrics: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._lock:
            self.step_no += 1
            record = {
                "runId": self.run_id,
                "stepNo": self.step_no,
                "stage": stage,
                "status": status,
                "inputSummary": input_summary,
                "outputSummary": output_summary,
                "metrics": metrics or {},
                "createdAt": _now_iso(),
            }
            self.records.append(record)
            with db_connection() as connection:
                connection.execute(
                    """
INSERT INTO create_run_steps (
  run_id, step_no, stage, status, input_summary, output_summary, metrics
)
VALUES (%s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (run_id, step_no) DO UPDATE SET
  stage = EXCLUDED.stage,
  status = EXCLUDED.status,
  input_summary = EXCLUDED.input_summary,
  output_summary = EXCLUDED.output_summary,
  metrics = EXCLUDED.metrics
""",
                    (
                        self.run_id,
                        self.step_no,
                        stage,
                        status,
                        input_summary,
                        output_summary,
                        Jsonb(metrics or {}),
                    ),
                )
            self.flush()
            publish_run_event(self.run_id, sanitize_step_event(record))
            return record

    def append_llm_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        metrics = payload.get("metrics") if isinstance(payload.get("metrics"), dict) else {}
        return self.append(
            stage="llm_call",
            status="succeeded",
            input_summary=str(metrics.get("promptPrefix", ""))[:500],
            output_summary=str(payload.get("outputPreview", ""))[:500],
            metrics={
                "iteration": payload.get("iteration"),
                "strategy": payload.get("strategy"),
                "topology": payload.get("topology"),
                "promptEnglishWords": metrics.get("promptEnglishWords"),
                "promptChineseChars": metrics.get("promptChineseChars"),
                "prefixEnglishWords": metrics.get("prefixEnglishWords"),
                "prefixChineseChars": metrics.get("prefixChineseChars"),
                "outputEnglishWords": metrics.get("outputEnglishWords"),
                "outputChineseChars": metrics.get("outputChineseChars"),
                "outputTokens": (metrics.get("tokenUsage") or {}).get("outputTokens"),
                "tokenUsage": metrics.get("tokenUsage"),
            },
        )

    def append_tool_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        tool = payload.get("tool") if isinstance(payload.get("tool"), dict) else {}
        result = payload.get("result") if isinstance(payload.get("result"), dict) else {}
        error = result.get("error") if isinstance(result.get("error"), dict) else None
        return self.append(
            stage="tool_call",
            status="succeeded" if result.get("ok") is True else "failed",
            input_summary=str(payload.get("requestSummary") or tool.get("name") or "Tool call")[:500],
            output_summary=str(payload.get("responseSummary") or (error or result))[:500],
            metrics={
                "iteration": payload.get("iteration"),
                "toolName": tool.get("name"),
                "files": payload.get("files") if isinstance(payload.get("files"), list) else [],
                "ok": result.get("ok"),
                "error": error,
            },
        )

    def flush(self) -> str:
        put_jsonl_object(self.object_key, self.records)
        return self.object_key
