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

    assert set(list_agent_strategies()) == {"chat", "decentralized", "plan", "react", "refine"}

    expected = {
        ("init", "chat"): "chat",
        ("init", "react"): "react",
        ("init", "plan"): "plan",
        ("opt", "chat"): "chat",
        ("opt", "react"): "react",
        ("opt", "plan"): "plan",
        ("opt", "decentralized"): "decentralized",
        ("opt", "refine"): "refine",
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
        if strategy_name == "decentralized":
            assert all(step.implemented is True for step in plan.steps)
            assert {step.name for step in plan.steps} == {
                "planner",
                "asset_agent",
                "game_code_agent",
                "build_agent",
                "safety_agent",
                "publisher_agent",
            }
            assert "stageContracts" in user_prompt
        else:
            assert all(step.implemented is False for step in plan.steps)
        assert system_prompt
        assert user_prompt
        assert payload["model"] == "test-model"
        assert callable(strategy.run_langgraph)
        assert '"type":"tool"' in system_prompt
        assert '"type":"final"' in system_prompt
        assert "window.parent.postMessage" in system_prompt
        assert "Never use parent.postMessage" in system_prompt
        assert "passive:false" in system_prompt
        if strategy_name == "plan":
            assert "Plan preview JSON reference" in system_prompt
            assert '"acceptanceChecks"' in system_prompt
            assert '"implementationSummary": "..."' not in system_prompt
        else:
            assert "Unified JSON response reference" in system_prompt
            assert '"workspacePath": "index.html"' in system_prompt
            assert '"implementationSummary": "..."' in system_prompt
            assert "The only allowed parent window reference" in system_prompt
        if strategy_name == "refine":
            assert "complete updated game package" in system_prompt
        assert "Do not execute tools in this strategy response" not in system_prompt
        assert "<tool" not in system_prompt
        assert "<final" not in system_prompt
        rendered = system_prompt + user_prompt
        for forbidden in ("Create type:", "Agent mode:", "Project ID:", "Run ID:", "Task ID:", "api_key"):
            assert forbidden not in rendered
        if create_type == "opt":
            assert "Continue optimization rules" in user_prompt
            assert "final output contract is identical to initial creation" in user_prompt
        if create_type == "init":
            assert "Initial creation rules" in user_prompt
        if strategy_name != "plan":
            assert "window.parent.postMessage" in rendered

    react = select_agent_strategy(context)
    react_system = react.system_prompt(context)
    assert '"type":"tool"' in react_system
    assert '"type":"final"' in react_system
    assert "The only allowed parent window reference" in react_system
    assert "Never use parent.postMessage" in react_system
    assert 'parent["postMessage"]' in react_system
    assert "globalThis.parent" in react_system
    assert "Never assign, cache, compare, read, or branch on window.parent" in react_system
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

    large_plan_settings = AgentRequestSettings(
        create_type="init",
        agent_mode="plan",
        user_request="make a planned game",
        persistent_memory_summary=[
            {
                "memoryType": "approved_plan",
                "payload": json.dumps(
                    {
                        "plan": [
                            {
                                "id": "step-1",
                                "title": "Build",
                                "goal": "G" * 4000,
                                "toolFamily": "workspace.*",
                                "expectedOutput": "E" * 4000,
                                "acceptanceCheckRefs": ["check-1"],
                            }
                        ],
                        "risks": ["R" * 3000],
                        "acceptanceChecks": [
                            {"id": "check-1", "description": "C" * 4000, "type": "runtime", "severity": "must"}
                        ],
                    },
                    ensure_ascii=False,
                ),
            }
        ],
    )
    large_plan_prompt = select_agent_strategy(large_plan_settings).user_prompt(large_plan_settings)
    assert "G" * 1000 not in large_plan_prompt
    assert "E" * 1000 not in large_plan_prompt
    assert "C" * 1000 not in large_plan_prompt
    assert "Approved plan:" in large_plan_prompt
    large_plan_system = select_agent_strategy(large_plan_settings).system_prompt(large_plan_settings)
    assert "Unified JSON response reference" in large_plan_system
    assert '"implementationSummary": "..."' in large_plan_system
    assert "The only allowed parent window reference" in large_plan_system

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

    react_wrapped = parse_main_agent_json_output(
        {
            "type": "final",
            "output": {
                "Finished": True,
                "files": [{"path": "index.html", "content": "<html><body>ok</body></html>"}],
                "cover": {"title": "Wrapped", "description": "", "tags": []},
            },
        }
    )
    assert react_wrapped["fallback"] is False
    assert "unwrapped_react_final_output" in react_wrapped["normalizationWarnings"]
    assert {entry["path"] for entry in react_wrapped["files"]} == {"index.html", "manifest.json", "source.json"}

    fenced = parse_main_agent_json_output(
        '```json\n{"type":"final","output":{"Finished":true,"files":[{"path":"index.html","content":"<html></html>"}]}}\n```'
    )
    assert fenced["fallback"] is False
    assert fenced["diagnostics"]["hasValidIndexHtml"] is True

    fallback = parse_main_agent_json_output("not json")
    assert fallback["fallback"] is True
    assert {entry["path"] for entry in fallback["files"]} == {"index.html", "manifest.json", "source.json"}

    missing_files = parse_main_agent_json_output({"files": [{"path": "index.html", "content": ""}]})
    assert missing_files["fallback"] is True
    assert missing_files["fallbackReason"] == "missing_or_empty_index_html"


if __name__ == "__main__":
    run()
    print("agent strategy checks passed")
