from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class AgentGraphResult:
    strategy: str
    topology: str
    finished: bool
    finish_reason: str
    iterations: int
    final_output: dict[str, Any] | None = None
    tool_results: list[dict[str, Any]] = field(default_factory=list)
    messages: list[dict[str, Any]] = field(default_factory=list)

