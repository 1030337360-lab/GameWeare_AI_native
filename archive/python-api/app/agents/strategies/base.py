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

UNIFIED_JSON_RESPONSE_REFERENCE = """Unified JSON response reference:

Tool call shape:
{
  "type": "tool",
  "tool": {
    "name": "workspace.file_write",
    "args": {
      "path": "index.html",
      "content": "..."
    }
  }
}

Final game package shape:
{
  "type": "final",
  "output": {
    "Finished": true,
    "files": [
      {
        "path": "index.html",
        "content": "..."
      },
      {
        "path": "manifest.json",
        "content": "{...}"
      },
      {
        "path": "source.json",
        "content": "{...}"
      }
    ],
    "cover": {
      "title": "...",
      "description": "...",
      "tags": ["..."]
    },
    "implementationSummary": "...",
    "safetyNotes": ["..."]
  }
}

Final game package shape when index.html was written through workspace.file_write:
{
  "type": "final",
  "output": {
    "Finished": true,
    "files": [
      {
        "path": "index.html",
        "workspacePath": "index.html"
      }
    ],
    "cover": {
      "title": "...",
      "description": "...",
      "tags": ["..."]
    },
    "implementationSummary": "...",
    "safetyNotes": ["..."]
  }
}
"""

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


def _short_text(value: Any, limit: int = 1200) -> str:
    text = value if isinstance(value, str) else _json(value)
    return text[:limit]


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


def _compact_history(history: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for item in history[-8:]:
        if not isinstance(item, dict):
            continue
        compact.append(
            {
                "role": item.get("role"),
                "content": _short_text(item.get("content", item.get("message", "")), 1600),
                "metadata": item.get("metadata") if isinstance(item.get("metadata"), dict) else {},
            }
        )
    return compact


def _compact_memory_item(item: dict[str, Any]) -> dict[str, Any]:
    memory_type = item.get("memoryType") or item.get("type")
    compact = {
        "memoryType": memory_type,
        "summary": _short_text(item.get("summary", ""), 1200),
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "objectKey": item.get("objectKey"),
        "sha256": item.get("sha256"),
    }
    payload = item.get("payload")
    if memory_type == "approved_plan" and isinstance(payload, str) and payload.strip():
        try:
            parsed_payload = json.loads(payload)
        except json.JSONDecodeError:
            parsed_payload = {}
        if isinstance(parsed_payload, dict):
            plan = parsed_payload.get("plan") if isinstance(parsed_payload.get("plan"), list) else []
            risks = parsed_payload.get("risks") if isinstance(parsed_payload.get("risks"), list) else []
            checks = parsed_payload.get("acceptanceChecks") if isinstance(parsed_payload.get("acceptanceChecks"), list) else []
            compact["payloadSummary"] = {
                "plan": [
                    {
                        "id": step.get("id"),
                        "title": _short_text(step.get("title", ""), 140),
                        "goal": _short_text(step.get("goal", ""), 260),
                        "toolFamily": _short_text(step.get("toolFamily", ""), 120),
                        "expectedOutput": _short_text(step.get("expectedOutput", ""), 260),
                        "acceptanceCheckRefs": step.get("acceptanceCheckRefs") if isinstance(step.get("acceptanceCheckRefs"), list) else [],
                    }
                    for step in plan[:8]
                    if isinstance(step, dict)
                ],
                "risks": [_short_text(risk, 220) for risk in risks[:8]],
                "acceptanceChecks": [
                    {
                        "id": check.get("id"),
                        "description": _short_text(check.get("description", ""), 260),
                        "type": _short_text(check.get("type", ""), 80),
                        "severity": _short_text(check.get("severity", ""), 80),
                    }
                    for check in checks[:12]
                    if isinstance(check, dict)
                ],
            }
            compact["payloadChars"] = len(payload)
            return {key: value for key, value in compact.items() if value not in (None, "", [])}
        compact["payloadPrefix"] = payload[:1200]
        compact["payloadChars"] = len(payload)
        return {key: value for key, value in compact.items() if value not in (None, "", [])}
    if isinstance(payload, str) and payload.strip():
        compact["payloadPrefix"] = payload[:4000]
        compact["payloadChars"] = len(payload)
    elif isinstance(payload, dict):
        compact["payloadPrefix"] = _json(payload)[:4000]
        compact["payloadChars"] = len(_json(payload))
    for key in ("gameSlug", "title", "versionNo", "entryFile", "workspaceFiles"):
        if key in item:
            compact[key] = item[key]
    if "previousIndexHtmlPrefix" in item:
        compact["previousIndexHtmlPrefix"] = _short_text(item.get("previousIndexHtmlPrefix", ""), 1800)
    if "previousSourceJson" in item:
        compact["previousSourceJsonPrefix"] = _short_text(item.get("previousSourceJson", ""), 1200)
    return {key: value for key, value in compact.items() if value not in (None, "", [])}


def _compact_memory(memory: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [_compact_memory_item(item) for item in memory[:12] if isinstance(item, dict)]


def _compact_tool_metadata(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for tool in tools[:40]:
        if not isinstance(tool, dict):
            continue
        compact.append(
            {
                "name": tool.get("name"),
                "category": tool.get("category"),
                "summary": _short_text(tool.get("summary", ""), 280),
                "inputSchema": tool.get("inputSchema") if isinstance(tool.get("inputSchema"), dict) else {},
                "sideEffects": tool.get("sideEffects") if isinstance(tool.get("sideEffects"), list) else [],
                "requires": tool.get("requires") if isinstance(tool.get("requires"), list) else [],
            }
        )
    return compact


def render_context_sections(settings: AgentRequestSettings) -> str:
    sections = [
        f"Create request: {settings.user_request}",
        f"Workspace capability: {_workspace_capability(settings.workspace_capability)}",
        f"Workspace boundary: {_workspace_boundary(settings.workspace_boundary)}",
    ]
    if settings.recent_8_history:
        sections.append(f"Recent conversation history: {_json(_compact_history(settings.recent_8_history))}")
    if settings.persistent_memory_summary:
        sections.append(f"Persistent memory summary: {_json(_compact_memory(settings.persistent_memory_summary))}")
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
    sections.append(f"Available tool metadata: {_json(_compact_tool_metadata(settings.tool_metadata))}")
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
- The final output contract is the standard Gameweare game package: index.html plus cover metadata, implementationSummary, and safetyNotes.
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
- Final output must satisfy the Gameweare game package JSON contract inside the output object.
- Final output must include Finished=true only when the complete game package is ready.
- For generated game files, prefer workspace.file_write before final output. Do not put large HTML/CSS/JS in final JSON.
- After writing files, final output may reference them as {{"path":"index.html","workspacePath":"index.html"}}.
- For a clean initial creation, do not call workspace.file_list first unless the user asks to inspect existing files.
- If there is no previous project context, directly generate the game or write index.html with workspace.file_write.
- When generating index.html, implement the Gameweare iframe runtime protocol exactly:
  window.parent.postMessage({{source:"gameweare-game",type:"game_ready",payload:{{...}}}}, "*") after the game can render.
  window.parent.postMessage({{source:"gameweare-game",type:"game_start",payload:{{...}}}}, "*") when the player starts or first meaningful input begins.
  window.parent.postMessage({{source:"gameweare-game",type:"game_end",payload:{{...}}}}, "*") when a run ends, wins, or fails.
  window.parent.postMessage({{source:"gameweare-game",type:"game_load_error",payload:{{message:String(error)}}}}, "*") if startup throws.
- The only allowed parent window reference in index.html is the exact member chain window.parent.postMessage(...).
- Never use parent.postMessage(...), parent["postMessage"](...), window["parent"], window?.parent, self.parent, globalThis.parent, parent.location, parent.document, window.parent.location, window.parent.document, or any parent property except postMessage.
- Never assign, cache, compare, read, or branch on window.parent; only call window.parent.postMessage(...) directly.
- Do not send lifecycle events without source:"gameweare-game"; do not put lifecycle fields only at the top level when a payload object is expected.
- Keyboard games must support Arrow keys and WASD when movement is requested, Space when an action such as bomb/place/jump/fire is requested, and call preventDefault for handled keys with passive:false listeners.
- Do not include markdown fences, XML tags, secrets, or backend-only identifiers.
{rendered_strategy_rules}

{UNIFIED_JSON_RESPONSE_REFERENCE}
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
            registry=registry,
            recorder=recorder,
        )
