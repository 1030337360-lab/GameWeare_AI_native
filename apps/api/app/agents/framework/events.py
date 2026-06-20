from __future__ import annotations

import json
from typing import Any

from app.services.auth_service import redis_client

RUN_EVENT_CHANNEL_PREFIX = "create:run-events:"
RUN_EVENT_TTL_SECONDS = 60 * 60 * 24


def run_event_channel(run_id: str) -> str:
    return f"{RUN_EVENT_CHANNEL_PREFIX}{run_id}"


def _safe_metrics(metrics: dict[str, Any]) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in metrics.items():
        if key.lower() in {"apikey", "api_key", "token", "secret", "authorization"}:
            continue
        if isinstance(value, (str, int, float, bool)) or value is None:
            safe[key] = value if not isinstance(value, str) else value[:1200]
        elif key in {"tokenUsage", "tool", "error", "raw", "planPreview", "previewState"} and isinstance(value, dict):
            safe[key] = {
                str(child_key): child_value
                for child_key, child_value in value.items()
                if isinstance(child_value, (str, int, float, bool, list, dict)) or child_value is None
            }
    return safe


def step_event_type(stage: str) -> str:
    if stage == "llm_call":
        return "llm_call"
    if stage == "tool_call":
        return "tool_call"
    if stage == "plan_ready":
        return "plan_ready"
    if stage == "decentralized_preview_ready":
        return "decentralized_preview_ready"
    if stage in {"run_completed", "job_completed"}:
        return "done"
    if stage in {"run_failed", "job_failed", "llm_generation_failed", "prompt_render_failed"}:
        return "error"
    return "step"


def sanitize_step_event(record: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": step_event_type(str(record.get("stage", ""))),
        "runId": record.get("runId"),
        "stepNo": record.get("stepNo"),
        "stage": record.get("stage"),
        "status": record.get("status"),
        "inputSummary": str(record.get("inputSummary") or "")[:800],
        "outputSummary": str(record.get("outputSummary") or "")[:800],
        "metrics": _safe_metrics(record.get("metrics") if isinstance(record.get("metrics"), dict) else {}),
        "createdAt": record.get("createdAt"),
    }


def publish_run_event(run_id: str, event: dict[str, Any]) -> None:
    client = redis_client()
    payload = json.dumps(event, ensure_ascii=False, default=str)
    channel = run_event_channel(run_id)
    client.publish(channel, payload)
    client.setex(f"{channel}:last", RUN_EVENT_TTL_SECONDS, payload)
