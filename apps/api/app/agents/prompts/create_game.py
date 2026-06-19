from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

CREATE_GAME_TEMPLATE_NAME = "yahaha-create-game"
CREATE_GAME_TEMPLATE_VERSION = "2026-06-19.1"
CONNECTION_TEST_TEMPLATE_NAME = "yahaha-connection-test"
CONNECTION_TEST_TEMPLATE_VERSION = "2026-06-19.1"
DEFAULT_REASONING_EFFORT = "medium"
DEFAULT_PERSONALITY = "pragmatic"
DEFAULT_CREATE_MAX_OUTPUT_TOKENS = 25000
DEFAULT_TEST_MAX_OUTPUT_TOKENS = 16

CREATE_TEMPLATE_FIELDS = [
    "user_request",
    "create_type",
    "agent_mode",
    "project_id",
    "run_id",
    "task_id",
    "recent_8_history",
    "workspace_capability",
    "workspace_boundary",
    "persistent_memory_summary",
]

SYSTEM_PROMPT = """You are the Yahaha Create Agent.
Generate a playable iframe HTML5 game package for the Yahaha platform.
Follow the platform contract strictly:
- Output a self-contained index.html game that can run in a sandboxed iframe.
- Use keyboard, mouse, pointer, and touch without scrolling the parent page.
- Do not request pointer lock.
- Use requestAnimationFrame for the game loop.
- Send postMessage events for game_ready, game_start, game_end, and game_load_error.
- Do not access secrets, backend-only APIs, local files, or privileged browser APIs.
- Return structured JSON only. Do not include markdown fences.
"""


@dataclass(frozen=True)
class CreatePromptContext:
    user_request: str
    create_type: str
    agent_mode: str
    project_id: str
    run_id: str
    task_id: str
    recent_8_history: list[dict[str, Any]] = field(default_factory=list)
    workspace_capability: str = "read_write"
    workspace_boundary: str = ""
    persistent_memory_summary: list[dict[str, Any]] = field(default_factory=list)


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, default=str)


def render_create_game_input(context: CreatePromptContext) -> str:
    return f"""Create request: {context.user_request}

Create type: {context.create_type}
Agent mode: {context.agent_mode}
Project ID: {context.project_id}
Run ID: {context.run_id}
Task ID: {context.task_id}

Recent conversation history: {_json(context.recent_8_history)}
Workspace capability: {context.workspace_capability}
Workspace boundary: {context.workspace_boundary}
Persistent memory summary: {_json(context.persistent_memory_summary)}

Required output JSON shape:
{{
  "files": [
    {{"path": "index.html", "content": "..."}},
    {{"path": "manifest.json", "content": "..."}},
    {{"path": "source.json", "content": "..."}}
  ],
  "cover": {{"title": "...", "description": "...", "tags": ["..."]}},
  "implementationSummary": "...",
  "safetyNotes": ["..."]
}}

Required files:
1. index.html as a self-contained playable game.
2. manifest.json with iframe-html5 or iframe-srcdoc runtime metadata.
3. source.json with prompt, implementation notes, and generated file list.
4. cover metadata.
5. short implementation summary.
6. safety notes.

Remember:
- Never include API keys or secrets.
- Never reference privileged local filesystem paths.
- Keep platform UI outside the iframe.
"""


def build_create_game_responses_payload(
    context: CreatePromptContext,
    model: str,
    max_output_tokens: int = DEFAULT_CREATE_MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [{"type": "input_text", "text": SYSTEM_PROMPT}],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": render_create_game_input(context)}],
            },
        ],
        "reasoning": {"effort": DEFAULT_REASONING_EFFORT},
        "max_output_tokens": max_output_tokens,
    }


def render_connection_test_payload(model: str) -> dict[str, Any]:
    return {
        "model": model,
        "input": [
            {
                "role": "system",
                "content": [
                    {
                        "type": "input_text",
                        "text": (
                            "You are an OpenAI Responses API connection test. "
                            f"Use a {DEFAULT_PERSONALITY} style and reply concisely."
                        ),
                    }
                ],
            },
            {
                "role": "user",
                "content": [{"type": "input_text", "text": "Reply with ok."}],
            },
        ],
        "reasoning": {"effort": DEFAULT_REASONING_EFFORT},
        "max_output_tokens": DEFAULT_TEST_MAX_OUTPUT_TOKENS,
    }


def template_metadata(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": CREATE_GAME_TEMPLATE_NAME,
        "version": CREATE_GAME_TEMPLATE_VERSION,
        "fields": CREATE_TEMPLATE_FIELDS,
        "wireApi": "responses",
        "inputMessages": len(payload.get("input", [])),
        "maxOutputTokens": payload.get("max_output_tokens"),
    }
