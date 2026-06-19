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
        create_type="init",
        agent_mode="plan",
        project_id="project-123",
        run_id="run-123",
        task_id="task-123",
        recent_8_history=[{"role": "user", "content": "make it bright"}],
        workspace_capability="read_write",
        workspace_boundary=".worktrees/create-run-123",
        persistent_memory_summary=[{"memoryType": "project_tag", "tags": ["arcade"]}],
    )

    rendered = render_create_game_input(context)
    assert "project-123" in rendered
    assert "run-123" in rendered
    assert "task-123" in rendered
    assert "api_key" not in rendered.lower()

    payload = build_create_game_responses_payload(context, "test-model")
    assert payload["model"] == "test-model"
    assert isinstance(payload["input"], list)
    assert payload["reasoning"]["effort"] == "medium"
    assert payload["max_output_tokens"] == 25000
    assert "api_key" not in json.dumps(payload).lower()

    metadata = template_metadata(payload)
    assert metadata["name"] == CREATE_GAME_TEMPLATE_NAME
    assert "project_id" in metadata["fields"]

    test_payload = render_connection_test_payload("test-model")
    assert test_payload["model"] == "test-model"
    assert test_payload["reasoning"]["effort"] == "medium"
    assert test_payload["max_output_tokens"] == 16


if __name__ == "__main__":
    run()
    print("prompt template checks passed")
