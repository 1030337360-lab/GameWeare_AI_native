from pathlib import Path
import json
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.create import parse_main_agent_json_output
from app.agents.strategies import AgentRequestSettings, list_agent_strategies, select_agent_strategy
from app.services.create_service import _is_multimodal_unsupported_error, _redacted_prompt_payload


def run() -> None:
    context = AgentRequestSettings(
        create_type="init",
        agent_mode="react",
        user_request="make a game",
        workspace_capability="read_write",
        workspace_boundary=".worktrees/create-demo",
        tool_metadata=[{"name": "workspace.file_read", "inputSchema": {"type": "object"}}],
    )

    assert set(list_agent_strategies()) == {"centralized", "decentralized", "plan", "react", "refine"}

    expected = {
        ("init", "react"): "react",
        ("init", "plan"): "plan",
        ("opt", "chat"): "refine",
        ("init", "centralized"): "centralized",
        ("init", "decentralized"): "decentralized",
    }
    for (create_type, agent_mode), strategy_name in expected.items():
        settings = AgentRequestSettings(**{**context.__dict__, "create_type": create_type, "agent_mode": agent_mode})
        strategy = select_agent_strategy(settings)
        plan = strategy.plan(settings)
        system_prompt = strategy.system_prompt(settings)
        user_prompt = strategy.user_prompt(settings)
        payload = strategy.build_responses_payload(settings, "test-model")
        assert plan.strategy == strategy_name
        assert plan.steps
        assert all(step.implemented is False for step in plan.steps)
        assert system_prompt
        assert user_prompt
        assert payload["model"] == "test-model"
        assert callable(strategy.run_langgraph)
        rendered = system_prompt + user_prompt
        for forbidden in ("Create type:", "Agent mode:", "Project ID:", "Run ID:", "Task ID:", "api_key"):
            assert forbidden not in rendered

    react = select_agent_strategy(context)
    react_system = react.system_prompt(context)
    assert '"type":"tool"' in react_system
    assert '"type":"final"' in react_system
    assert "<tool" not in react_system
    assert "<final" not in react_system

    image_settings = AgentRequestSettings(
        create_type="init",
        agent_mode="plan",
        user_request="make a game from this screenshot",
        input_assets=[
            {
                "assetId": "asset-test",
                "filename": "sketch.png",
                "contentType": "image/png",
                "size": 12,
                "dataUrl": "data:image/png;base64,AAAA",
            }
        ],
    )
    image_payload = select_agent_strategy(image_settings).build_responses_payload(image_settings, "test-model")
    user_content = image_payload["input"][1]["content"]
    assert any(item.get("type") == "input_image" and item.get("image_url") == "data:image/png;base64,AAAA" for item in user_content)
    rendered_payload = json.dumps(image_payload, ensure_ascii=False)
    assert "sketch.png" in rendered_payload
    assert "api_key" not in rendered_payload
    redacted_payload = _redacted_prompt_payload(image_payload)
    redacted_text = json.dumps(redacted_payload, ensure_ascii=False)
    assert "data:image/png;base64,AAAA" not in redacted_text
    assert "[image omitted]" in redacted_text
    assert _is_multimodal_unsupported_error({"error": {"message": "This model does not support image input."}})

    valid = {
        "files": [
            {"path": "index.html", "content": "<html></html>"},
            {"path": "manifest.json", "content": "{}"},
            {"path": "source.json", "content": "{}"},
        ],
        "cover": {"title": "Demo", "description": "", "tags": []},
        "implementationSummary": "done",
        "safetyNotes": [],
    }
    parsed = parse_main_agent_json_output(json.dumps(valid))
    assert parsed["fallback"] is False
    assert parsed["files"][0]["path"] == "index.html"

    fallback = parse_main_agent_json_output("not json")
    assert fallback["fallback"] is True
    assert {entry["path"] for entry in fallback["files"]} == {"index.html", "manifest.json", "source.json"}

    missing_files = parse_main_agent_json_output({"files": [{"path": "index.html", "content": ""}]})
    assert missing_files["fallback"] is True
    assert missing_files["fallbackReason"] == "missing_required_files"


if __name__ == "__main__":
    run()
    print("agent strategy checks passed")
