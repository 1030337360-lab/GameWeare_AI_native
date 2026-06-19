from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class LongTermMemoryRecorder(Protocol):
    def append_history(self, role: str, content: str, metadata: dict[str, Any] | None = None) -> None:
        ...


class ShortTermMemoryRecorder(Protocol):
    def record_llm_call(self, payload: dict[str, Any]) -> None:
        ...


class RunLogRecorder(Protocol):
    def append_llm_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...

    def append_tool_call(self, payload: dict[str, Any]) -> dict[str, Any]:
        ...


@dataclass(frozen=True)
class LLMCallRecorder:
    long_term_memory: LongTermMemoryRecorder | None = None
    short_term_memory: ShortTermMemoryRecorder | None = None
    run_log: RunLogRecorder | None = None

    def record(self, event: dict[str, Any]) -> None:
        payload = {**event, "recordedAt": _now_iso()}
        if self.long_term_memory:
            self.long_term_memory.append_history(
                "llm",
                event.get("outputText", ""),
                metadata={
                    "kind": "llm_call",
                    "iteration": event.get("iteration"),
                    "metrics": event.get("metrics", {}),
                },
            )
        if self.short_term_memory:
            self.short_term_memory.record_llm_call(payload)
        if self.run_log:
            self.run_log.append_llm_call(payload)

    def record_tool_call(self, event: dict[str, Any]) -> None:
        payload = {**event, "recordedAt": _now_iso()}
        if self.short_term_memory:
            self.short_term_memory.record_llm_call(payload)
        if self.run_log:
            self.run_log.append_tool_call(payload)


def build_llm_call_event(
    *,
    strategy: str,
    topology: str,
    iteration: int,
    output_text: str,
    metrics: dict[str, Any],
    raw: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "kind": "llm_call",
        "strategy": strategy,
        "topology": topology,
        "iteration": iteration,
        "outputText": output_text,
        "outputPreview": output_text[:600],
        "metrics": metrics,
        "raw": raw or {},
    }
