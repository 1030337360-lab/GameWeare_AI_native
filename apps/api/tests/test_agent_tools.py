from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.tools import build_builtin_tool_registry


def run() -> None:
    registry = build_builtin_tool_registry()
    metadata = registry.list_metadata()
    assert metadata

    names = {tool["name"] for tool in metadata}
    assert "workspace.file_read" in names
    assert "workspace.file_list" in names
    assert "llm.prompt_render" in names
    assert "memory.summary_build" in names
    assert "run_log.preview_step" in names
    assert "command.plan" in names
    assert "git.worktree_plan" in names
    assert "storage.object_key_plan" in names
    assert "database.query_plan" in names
    assert "test.plan" in names
    assert "web.fetch_plan" in names

    for tool in metadata:
        assert tool["inputSchema"]["type"] == "object"
        assert tool["outputSchema"]["type"] == "object"
        assert tool["examples"], tool["name"]
        assert isinstance(tool["sideEffects"], list)
        assert isinstance(tool["requires"], list)
        assert tool["requires"], tool["name"]
        for example in tool["examples"]:
            assert isinstance(example["input"], dict)

    example_results = registry.run_examples()
    assert len(example_results) == sum(len(tool["examples"]) for tool in metadata)
    assert all(result["ok"] is True for result in example_results)

    read_result = registry.call("workspace.file_read", {"path": "app/main.py", "maxBytes": 2000})
    assert read_result["ok"] is True
    assert read_result["data"]["path"] == "app/main.py"
    assert read_result["data"]["sha256"]

    prompt_result = registry.call(
        "llm.prompt_render",
        {
            "userRequest": "Create a tiny game.",
            "createType": "init",
            "agentMode": "react",
            "model": "gpt-5.5",
        },
    )
    assert prompt_result["data"]["wireApi"] == "responses"
    assert prompt_result["data"]["payload"]["model"] == "gpt-5.5"
    prompt_payload_text = str(prompt_result["data"]["payload"])
    assert "project-test" not in prompt_payload_text
    assert "run-test" not in prompt_payload_text
    assert "task-test" not in prompt_payload_text
    assert "Create type:" not in prompt_payload_text
    assert "Agent mode:" not in prompt_payload_text
    assert '"type":"tool"' in prompt_payload_text
    assert '"type":"final"' in prompt_payload_text
    assert "<tool" not in prompt_payload_text

    planned_command = registry.call(
        "command.plan",
        {"args": [".venv\\Scripts\\python", "tests\\test_agent_tools.py"], "cwd": "apps/api"},
    )
    assert planned_command["data"]["dryRun"] is True
    assert planned_command["data"]["shell"] is False

    planned_storage = registry.call(
        "storage.object_key_plan",
        {"purpose": "task-state", "filename": "task-state.json", "userId": "u1", "projectId": "p1"},
    )
    assert planned_storage["data"]["objectKey"].startswith("agent-memory/u1/p1/task-state/")

    planned_query = registry.call("database.query_plan", {"entity": "run", "filters": {"projectId": "p1"}})
    assert planned_query["data"]["table"] == "create_runs"

    planned_web = registry.call("web.fetch_plan", {"url": "https://www.astrocade.com/"})
    assert planned_web["data"]["schemeAllowed"] is True

    validation_error = registry.call("llm.prompt_render", {})
    assert validation_error["ok"] is False
    assert validation_error["error"]["code"] == "TOOL_VALIDATION_ERROR"
    assert validation_error["error"]["tool"] == "llm.prompt_render"
    assert validation_error["error"]["request"]["input"] == {}

    permission_error = registry.call("workspace.file_read", {"path": "../README.md"})
    assert permission_error["ok"] is False
    assert permission_error["error"]["code"] == "TOOL_PERMISSION_ERROR"
    assert permission_error["error"]["tool"] == "workspace.file_read"
    assert permission_error["error"]["request"]["input"] == {"path": "../README.md"}
    assert permission_error["error"]["files"] == ["../README.md"]

    missing_tool = registry.call("missing.tool", {"file": "demo.txt"})
    assert missing_tool["ok"] is False
    assert missing_tool["error"]["code"] == "TOOL_NOT_FOUND"
    assert missing_tool["error"]["files"] == ["demo.txt"]


if __name__ == "__main__":
    run()
    print("agent tool checks passed")
