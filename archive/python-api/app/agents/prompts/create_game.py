from __future__ import annotations

from typing import Any

from app.agents.strategies import AgentRequestSettings, select_agent_strategy

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
    "recent_8_history",
    "workspace_capability",
    "workspace_boundary",
    "persistent_memory_summary",
    "tool_metadata",
]

CreatePromptContext = AgentRequestSettings


def render_create_game_input(context: CreatePromptContext) -> str:
    return select_agent_strategy(context).user_prompt(context)


def build_create_game_responses_payload(
    context: CreatePromptContext,
    model: str,
    max_output_tokens: int = DEFAULT_CREATE_MAX_OUTPUT_TOKENS,
) -> dict[str, Any]:
    return select_agent_strategy(context).build_responses_payload(context, model, max_output_tokens)


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
