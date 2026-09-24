from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.prompts import (
    CREATE_GAME_TEMPLATE_NAME,
    CreatePromptContext,
    build_create_game_responses_payload,
    render_connection_test_payload,
    render_create_game_input,
    template_metadata,
)


def run() -> None:
    context = CreatePromptContext(
        user_request="make a rhythm platformer",
        recent_8_history=[{"role": "user", "content": "make it bright"}],
        workspace_capability="read_write",
        workspace_boundary=".worktrees/create-run-123",
        persistent_memory_summary=[{"memoryType": "project_tag", "tags": ["arcade"]}],
        tool_metadata=[{"name": "workspace.file_read", "inputSchema": {"type": "object"}}],
    )

    rendered = render_create_game_input(context)
    assert "workspace.file_read" in rendered
    assert "Recent conversation history:" in rendered
    assert "Persistent memory summary:" in rendered
    assert "Workspace capability: read_write" in rendered
    assert "Workspace boundary: .worktrees/create-run-123" in rendered
    assert "Create type:" not in rendered
    assert "Agent mode:" not in rendered
    assert "Project ID:" not in rendered
    assert "Run ID:" not in rendered
    assert "Task ID:" not in rendered
    assert "api_key" not in rendered.lower()

    empty_context = CreatePromptContext(
        user_request="make a puzzle",
        workspace_capability="",
        workspace_boundary="",
    )
    empty_rendered = render_create_game_input(empty_context)
    assert "Recent conversation history:" not in empty_rendered
    assert "Persistent memory summary:" not in empty_rendered
    assert "Workspace capability: read_write" in empty_rendered
    assert "Workspace boundary: .worktrees/create-main" in empty_rendered

    payload = build_create_game_responses_payload(context, "test-model")
    assert payload["model"] == "test-model"
    assert isinstance(payload["input"], list)
    assert payload["reasoning"]["effort"] == "medium"
    assert payload["max_output_tokens"] == 25000
    payload_text = json.dumps(payload, ensure_ascii=False)
    assert "api_key" not in payload_text.lower()
    assert "createType" not in payload_text
    assert "agentMode" not in payload_text
    assert "<tool" not in payload_text
    assert "<final" not in payload_text

    metadata = template_metadata(payload)
    assert metadata["name"] == CREATE_GAME_TEMPLATE_NAME
    assert "project_id" not in metadata["fields"]
    assert "run_id" not in metadata["fields"]
    assert "task_id" not in metadata["fields"]
    assert "create_type" not in metadata["fields"]
    assert "agent_mode" not in metadata["fields"]

    test_payload = render_connection_test_payload("test-model")
    assert test_payload["model"] == "test-model"
    assert test_payload["reasoning"]["effort"] == "medium"
    assert test_payload["max_output_tokens"] == 16


if __name__ == "__main__":
    run()
    print("prompt template checks passed")
