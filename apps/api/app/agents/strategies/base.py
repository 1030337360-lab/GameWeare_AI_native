from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from app.agents.graphs.llm_adapter import LLMGraphAdapter
    from app.agents.graphs.recording import LLMCallRecorder
    from app.agents.graphs.types import AgentGraphResult
    from app.agents.tools import ToolRegistry

DEFAULT_WORKSPACE_CAPABILITY = "read_write"
DEFAULT_WORKSPACE_BOUNDARY = ".worktrees/create-main"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_MAX_OUTPUT_TOKENS = 25000

OUTPUT_JSON_CONTRACT = """Required game package fields:
{
  "files": [
    {"path": "index.html", "content": "..."}
  ],
  "cover": {"title": "...", "description": "...", "tags": ["..."]},
  "implementationSummary": "...",
  "safetyNotes": ["..."]
}
For ReAct final responses, place these game package fields inside output:
{"type":"final","output":{"Finished":true,"files":[...],"cover":{...},"implementationSummary":"...","safetyNotes":[...]}}
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
    input_assets: list[dict[str, Any]] = field(default_factory=list)

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
        input_assets: list[dict[str, Any]] | None = None,
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
            input_assets=input_assets or [],
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

    def run_langgraph(
        self,
        *,
        settings: AgentRequestSettings,
        model: str,
        adapter: LLMGraphAdapter,
        registry: ToolRegistry | None = None,
        recorder: LLMCallRecorder | None = None,
    ) -> AgentGraphResult:
        ...


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def _workspace_capability(value: str | None) -> str:
    return value.strip() if value and value.strip() else DEFAULT_WORKSPACE_CAPABILITY


def _workspace_boundary(value: str | None) -> str:
    return value.strip() if value and value.strip() else DEFAULT_WORKSPACE_BOUNDARY


def steps(items: list[tuple[str, str, str] | tuple[str, str, str, bool]]) -> list[AgentStrategyStep]:
    normalized: list[AgentStrategyStep] = []
    for item in items:
        name, description, tool = item[:3]
        implemented = bool(item[3]) if len(item) > 3 else False
        normalized.append(AgentStrategyStep(name=name, description=description, tool_contract=tool, implemented=implemented))
    return normalized


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
    if settings.input_assets:
        sections.append(
            "User input images: "
            + _json(
                [
                    {
                        "assetId": asset.get("assetId"),
                        "filename": asset.get("filename"),
                        "contentType": asset.get("contentType"),
                        "size": asset.get("size"),
                    }
                    for asset in settings.input_assets
                ]
            )
        )
    sections.append(f"Available tool metadata: {_json(settings.tool_metadata)}")
    return "\n".join(sections)


def is_continue_create(settings: AgentRequestSettings) -> bool:
    return (settings.create_type or "init").strip().lower() == "opt"


def render_create_intent_rules(settings: AgentRequestSettings) -> str:
    if is_continue_create(settings):
        return """Continue optimization rules:
- This is a continuation of an existing creator project.
- Use the injected persistent memory summary and workspace files as the previous version context.
- Preserve working behavior from the previous version unless the creator explicitly asks to change it.
- Produce a complete next version of the game, not a patch, diff, or advice-only response.
- The final output contract is identical to initial creation: one playable game package with index.html plus cover metadata, implementationSummary, and safetyNotes.
- Do not expose backend IDs or internal route fields in the prompt or output."""
    return """Initial creation rules:
- This is a new creator project.
- Create the first complete playable game from the creator request and available input assets.
- The final output contract is the standard Yahaha game package: index.html plus cover metadata, implementationSummary, and safetyNotes.
- Do not expose backend IDs or internal route fields in the prompt or output."""


def render_shared_game_contract() -> str:
    return f"""{OUTPUT_JSON_CONTRACT}
Runtime requirements:
- index.html must be a self-contained iframe HTML5 game.
- files must be a non-empty array of objects with string path and string content.
- files must include index.html; include manifest.json and source.json when possible, but the backend can synthesize them.
- Use keyboard, mouse, pointer, and touch without scrolling the parent page.
- Do not request pointer lock.
- Use requestAnimationFrame for the game loop.
- Send postMessage events for game_ready, game_start, game_end, and game_load_error.
- Do not access secrets, backend-only APIs, local files, or privileged browser APIs.
- Return structured JSON only. Do not include markdown fences.
"""


def render_json_tool_final_rules(*, identity: str, strategy_rules: list[str]) -> str:
    rendered_strategy_rules = "\n".join(f"- {rule}" for rule in strategy_rules)
    return f"""You are the {identity}, a local game-generation coding agent working inside a bounded workspace.

Rules:
- Use tools instead of guessing about the workspace.
- Return exactly one JSON object.
- For a tool call, return {{"type":"tool","tool":{{"name":"tool_name","args":{{...}}}}}}.
- For a final answer, return {{"type":"final","output":{{"Finished":true,"files":[...],"cover":{{...}},"implementationSummary":"...","safetyNotes":[...]}}}}.
- Tool args must be non-empty and must match the declared tool metadata schema.
- Never invent tool results.
- Do not repeat the same tool call with the same arguments if it did not help.
- Before proposing edits or tests for existing code, inspect the relevant implementation through tools.
- Final output must satisfy the Yahaha game package JSON contract inside the output object.
- Final output must include Finished=true only when the complete game package is ready.
- For generated game files, prefer workspace.file_write before final output. Do not put large HTML/CSS/JS in final JSON.
- After writing files, final output may reference them as {{"path":"index.html","workspacePath":"index.html"}}.
- Do not include markdown fences, XML tags, secrets, or backend-only identifiers.
{rendered_strategy_rules}
"""


def build_payload(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: int = DEFAULT_MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    user_content: list[dict[str, Any]] = [{"type": "input_text", "text": user_prompt}]
    return {
        "model": model,
        "input": [
            {"role": "system", "content": [{"type": "input_text", "text": system_prompt}]},
            {"role": "user", "content": user_content},
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
        payload = build_payload(
            model=model,
            system_prompt=self.system_prompt(settings),
            user_prompt=self.user_prompt(settings),
            max_output_tokens=max_output_tokens,
        )
        if settings.input_assets:
            user_message = payload["input"][1]
            content = user_message["content"]
            for asset in settings.input_assets:
                data_url = asset.get("dataUrl")
                if isinstance(data_url, str) and data_url:
                    content.append({"type": "input_image", "image_url": data_url})
        return payload

    def run_langgraph(
        self,
        *,
        settings: AgentRequestSettings,
        model: str,
        adapter: LLMGraphAdapter,
        registry: ToolRegistry | None = None,
        recorder: LLMCallRecorder | None = None,
    ) -> AgentGraphResult:
        from app.agents.graphs.single_step_graph import run_single_step_graph

        return run_single_step_graph(
            strategy=self,
            settings=settings,
            model=model,
            adapter=adapter,
            recorder=recorder,
        )
