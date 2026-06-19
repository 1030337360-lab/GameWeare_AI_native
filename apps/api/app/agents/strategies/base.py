from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any, Protocol

DEFAULT_WORKSPACE_CAPABILITY = "read_write"
DEFAULT_WORKSPACE_BOUNDARY = ".worktrees/create-main"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_MAX_OUTPUT_TOKENS = 25000

OUTPUT_JSON_CONTRACT = """Required final output JSON shape:
{
  "files": [
    {"path": "index.html", "content": "..."},
    {"path": "manifest.json", "content": "..."},
    {"path": "source.json", "content": "..."}
  ],
  "cover": {"title": "...", "description": "...", "tags": ["..."]},
  "implementationSummary": "...",
  "safetyNotes": ["..."]
}
"""


@dataclass(frozen=True)
class AgentRequestSettings:
    user_request: str
    create_type: str = "init"
    agent_mode: str = "chat"
    workspace_capability: str = DEFAULT_WORKSPACE_CAPABILITY
    workspace_boundary: str = DEFAULT_WORKSPACE_BOUNDARY
    recent_8_history: list[dict[str, Any]] = field(default_factory=list)
    persistent_memory_summary: list[dict[str, Any]] = field(default_factory=list)
    tool_metadata: list[dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_create_context(
        cls,
        *,
        user_request: str,
        create_type: str,
        agent_mode: str,
        workspace_capability: str | None,
        workspace_boundary: str | None,
        recent_8_history: list[dict[str, Any]] | None = None,
        persistent_memory_summary: list[dict[str, Any]] | None = None,
        tool_metadata: list[dict[str, Any]] | None = None,
    ) -> "AgentRequestSettings":
        return cls(
            user_request=user_request,
            create_type=create_type,
            agent_mode=agent_mode,
            workspace_capability=_workspace_capability(workspace_capability),
            workspace_boundary=_workspace_boundary(workspace_boundary),
            recent_8_history=recent_8_history or [],
            persistent_memory_summary=persistent_memory_summary or [],
            tool_metadata=tool_metadata or [],
        )


@dataclass(frozen=True)
class AgentStrategyStep:
    name: str
    description: str
    tool_contract: str
    implemented: bool = False


@dataclass(frozen=True)
class AgentStrategyPlan:
    strategy: str
    topology: str
    create_type: str
    agent_mode: str
    steps: list[AgentStrategyStep] = field(default_factory=list)

    def to_metadata(self) -> dict[str, Any]:
        return {
            "strategy": self.strategy,
            "topology": self.topology,
            "createType": self.create_type,
            "agentMode": self.agent_mode,
            "steps": [
                {
                    "name": step.name,
                    "description": step.description,
                    "toolContract": step.tool_contract,
                    "implemented": step.implemented,
                }
                for step in self.steps
            ],
        }


class AgentStrategy(Protocol):
    name: str
    topology: str

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        ...

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        ...

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        ...

    def build_responses_payload(
        self,
        settings: AgentRequestSettings,
        model: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        ...


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _workspace_capability(value: str | None) -> str:
    return value.strip() if value and value.strip() else DEFAULT_WORKSPACE_CAPABILITY


def _workspace_boundary(value: str | None) -> str:
    return value.strip() if value and value.strip() else DEFAULT_WORKSPACE_BOUNDARY


def steps(items: list[tuple[str, str, str]]) -> list[AgentStrategyStep]:
    return [AgentStrategyStep(name=name, description=description, tool_contract=tool) for name, description, tool in items]


def render_context_sections(settings: AgentRequestSettings) -> str:
    sections = [
        f"Create request: {settings.user_request}",
        f"Workspace capability: {_workspace_capability(settings.workspace_capability)}",
        f"Workspace boundary: {_workspace_boundary(settings.workspace_boundary)}",
    ]
    if settings.recent_8_history:
        sections.append(f"Recent conversation history: {_json(settings.recent_8_history)}")
    if settings.persistent_memory_summary:
        sections.append(f"Persistent memory summary: {_json(settings.persistent_memory_summary)}")
    sections.append(f"Available tool metadata: {_json(settings.tool_metadata)}")
    return "\n".join(sections)


def render_shared_game_contract() -> str:
    return f"""{OUTPUT_JSON_CONTRACT}
Runtime requirements:
- index.html must be a self-contained iframe HTML5 game.
- Use keyboard, mouse, pointer, and touch without scrolling the parent page.
- Do not request pointer lock.
- Use requestAnimationFrame for the game loop.
- Send postMessage events for game_ready, game_start, game_end, and game_load_error.
- Do not access secrets, backend-only APIs, local files, or privileged browser APIs.
- Return structured JSON only. Do not include markdown fences.
"""


def build_payload(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": [{"type": "input_text", "text": user_prompt}]},
        ],
        "reasoning": {"effort": DEFAULT_REASONING_EFFORT},
        "max_output_tokens": max_output_tokens,
    }


class BaseAgentStrategy:
    name = "base"
    topology = "single-agent"

    def plan(self, settings: AgentRequestSettings) -> AgentStrategyPlan:
        return AgentStrategyPlan(
            strategy=self.name,
            topology=self.topology,
            create_type=settings.create_type,
            agent_mode=settings.agent_mode,
            steps=[],
        )

    def system_prompt(self, settings: AgentRequestSettings) -> str:
        raise NotImplementedError

    def user_prompt(self, settings: AgentRequestSettings) -> str:
        return f"""{render_context_sections(settings)}

{render_shared_game_contract()}
"""

    def build_responses_payload(
        self,
        settings: AgentRequestSettings,
        model: str,
        max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
    ) -> dict[str, Any]:
        return build_payload(
            model=model,
            system_prompt=self.system_prompt(settings),
            user_prompt=self.user_prompt(settings),
            max_output_tokens=max_output_tokens,
        )
