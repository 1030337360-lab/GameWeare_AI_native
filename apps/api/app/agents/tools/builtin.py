from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from app.agents.framework.workspace import WorkspaceContext, WorkspaceFS
from app.agents.strategies import AgentRequestSettings, select_agent_strategy
from app.agents.tools.registry import ToolExample, ToolRegistry, ToolSpec, tool_result


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[3]


def _demo_workspace_context() -> WorkspaceContext:
    root = _repo_root()
    return WorkspaceContext(
        run_id="tool-demo-run",
        project_id="tool-demo-project",
        workspace_root=str(root),
        worktree_stub_path=str(root / ".worktrees" / "tool-demo-run"),
        branch_name=None,
        base_commit=None,
        cleanup_policy="manual",
        isolation_mode="stub",
        capability="read_only",
        status="prepared",
    )


def _file_read(payload: dict[str, Any]) -> dict[str, Any]:
    fs = WorkspaceFS(_demo_workspace_context())
    content = fs.read_text(payload["path"])
    limit = payload.get("maxBytes", 20000)
    encoded = content.encode("utf-8")
    truncated = len(encoded) > limit
    if truncated:
        content = encoded[:limit].decode("utf-8", errors="ignore")
    return tool_result(
        ok=True,
        data={
            "path": payload["path"],
            "content": content,
            "sha256": hashlib.sha256(encoded).hexdigest(),
            "bytes": len(encoded),
            "truncated": truncated,
        },
    )


def _file_list(payload: dict[str, Any]) -> dict[str, Any]:
    fs = WorkspaceFS(_demo_workspace_context())
    files = fs.list_files(payload.get("path", "."))
    limit = payload.get("limit", 200)
    return tool_result(
        ok=True,
        data={
            "path": payload.get("path", "."),
            "files": files[:limit],
            "total": len(files),
            "truncated": len(files) > limit,
        },
    )


def _prompt_render(payload: dict[str, Any]) -> dict[str, Any]:
    settings = AgentRequestSettings.from_create_context(
        user_request=payload["userRequest"],
        create_type=payload.get("createType", "init"),
        agent_mode=payload.get("agentMode", "chat"),
        recent_8_history=payload.get("recent8History", []),
        workspace_capability=payload.get("workspaceCapability", "read_write"),
        workspace_boundary=payload.get("workspaceBoundary", ".worktrees/create-demo"),
        persistent_memory_summary=payload.get("persistentMemorySummary", []),
        tool_metadata=payload.get("toolMetadata", []),
        input_assets=payload.get("inputAssets", []),
    )
    strategy = select_agent_strategy(settings)
    response_payload = strategy.build_responses_payload(
        settings,
        payload.get("model", "gpt-5.5"),
        max_output_tokens=payload.get("maxOutputTokens", 25000),
    )
    return tool_result(
        ok=True,
        data={
            "wireApi": "responses",
            "payload": response_payload,
            "template": {"name": "create_game", "version": "1", "strategy": strategy.name},
        },
    )


def _memory_summarize(payload: dict[str, Any]) -> dict[str, Any]:
    entries = payload.get("entries", [])
    tags: list[str] = []
    for entry in entries:
        for tag in entry.get("tags", []):
            if tag not in tags:
                tags.append(tag)
    return tool_result(
        ok=True,
        data={
            "count": len(entries),
            "tags": tags,
            "summary": "; ".join(entry.get("summary", "") for entry in entries if entry.get("summary"))[:1000],
        },
    )


def _run_log_preview(payload: dict[str, Any]) -> dict[str, Any]:
    return tool_result(
        ok=True,
        data={
            "runId": payload["runId"],
            "stage": payload["stage"],
            "status": payload.get("status", "succeeded"),
            "inputSummary": payload.get("inputSummary", ""),
            "outputSummary": payload.get("outputSummary", ""),
            "metrics": payload.get("metrics", {}),
            "dryRun": True,
        },
    )


def _command_plan(payload: dict[str, Any]) -> dict[str, Any]:
    args = payload["args"]
    cwd = payload.get("cwd", ".")
    timeout_seconds = payload.get("timeoutSeconds", 60)
    return tool_result(
        ok=True,
        data={
            "args": args,
            "cwd": cwd,
            "timeoutSeconds": timeout_seconds,
            "shell": False,
            "dryRun": True,
            "execution": "deferred",
        },
    )


def _git_worktree_plan(payload: dict[str, Any]) -> dict[str, Any]:
    run_id = payload["runId"]
    base_ref = payload.get("baseRef", "HEAD")
    branch_name = payload.get("branchName", f"codex/create-{run_id}")
    path = payload.get("path", f".worktrees/create-{run_id}")
    return tool_result(
        ok=True,
        data={
            "runId": run_id,
            "baseRef": base_ref,
            "branchName": branch_name,
            "path": path,
            "commands": [
                ["git", "rev-parse", base_ref],
                ["git", "worktree", "add", path, "-b", branch_name, base_ref],
            ],
            "dryRun": True,
        },
    )


def _storage_object_plan(payload: dict[str, Any]) -> dict[str, Any]:
    purpose = payload["purpose"]
    owner_id = payload.get("userId", "user-demo")
    project_id = payload.get("projectId", "project-demo")
    filename = payload["filename"].lstrip("/").replace("\\", "/")
    safe_filename = re.sub(r"[^A-Za-z0-9._/-]+", "-", filename).strip("-") or "object.json"
    object_key = f"agent-memory/{owner_id}/{project_id}/{purpose}/{safe_filename}"
    return tool_result(
        ok=True,
        data={
            "bucketRole": "configured-minio-bucket",
            "objectKey": object_key,
            "contentType": payload.get("contentType", "application/json"),
            "metadata": payload.get("metadata", {}),
            "dryRun": True,
        },
    )


def _database_query_plan(payload: dict[str, Any]) -> dict[str, Any]:
    entity = payload["entity"]
    operation = payload.get("operation", "select")
    allowed_entities = {
        "game": "games",
        "project": "agent_projects",
        "run": "create_runs",
        "asset": "assets",
        "memory": "agent_memory_index",
    }
    table = allowed_entities[entity]
    return tool_result(
        ok=True,
        data={
            "entity": entity,
            "table": table,
            "operation": operation,
            "filters": payload.get("filters", {}),
            "limit": payload.get("limit", 50),
            "dryRun": True,
        },
    )


def _test_plan(payload: dict[str, Any]) -> dict[str, Any]:
    suite = payload["suite"]
    commands = {
        "agent_tools": [".venv\\Scripts\\python", "tests\\test_agent_tools.py"],
        "prompt_templates": [".venv\\Scripts\\python", "tests\\test_prompt_templates.py"],
        "workspace_isolation": [".venv\\Scripts\\python", "tests\\test_workspace_isolation.py"],
        "llm_service": [".venv\\Scripts\\python", "tests\\test_llm_service.py"],
    }
    return tool_result(
        ok=True,
        data={
            "suite": suite,
            "command": commands[suite],
            "cwd": payload.get("cwd", "apps/api"),
            "expectedResult": "exit_code_0",
            "dryRun": True,
        },
    )


def _web_fetch_plan(payload: dict[str, Any]) -> dict[str, Any]:
    url = payload["url"]
    parsed_scheme = url.split(":", 1)[0].lower()
    return tool_result(
        ok=True,
        data={
            "url": url,
            "method": payload.get("method", "GET"),
            "allowedSchemes": ["http", "https"],
            "schemeAllowed": parsed_scheme in {"http", "https"},
            "purpose": payload.get("purpose", "reference"),
            "dryRun": True,
        },
    )


JSON_RESULT_SCHEMA = {
    "type": "object",
    "required": ["ok", "data", "error"],
    "properties": {
        "ok": {"type": "boolean"},
        "data": {"type": "object"},
        "error": {"type": ["object", "null"]},
    },
    "additionalProperties": False,
}


def build_builtin_tool_registry() -> ToolRegistry:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="workspace.file_read",
            category="basic",
            summary="Read a UTF-8 text file inside the active workspace boundary.",
            input_schema={
                "type": "object",
                "required": ["path"],
                "properties": {
                    "path": {"type": "string"},
                    "maxBytes": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="read_api_main",
                    description="Read the FastAPI entry file through the workspace boundary.",
                    input={"path": "app/main.py", "maxBytes": 12000},
                )
            ],
            handler=_file_read,
            side_effects=[],
            requires=["workspace.read"],
        )
    )
    registry.register(
        ToolSpec(
            name="workspace.file_list",
            category="basic",
            summary="List files inside the active workspace boundary.",
            input_schema={
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="list_agent_modules",
                    description="List files in the agent package.",
                    input={"path": "app/agents", "limit": 100},
                )
            ],
            handler=_file_list,
            side_effects=[],
            requires=["workspace.read"],
        )
    )
    registry.register(
        ToolSpec(
            name="llm.prompt_render",
            category="basic",
            summary="Render the Create game prompt payload without calling the LLM provider.",
            input_schema={
                "type": "object",
                "required": ["userRequest"],
                "properties": {
                    "userRequest": {"type": "string"},
                    "createType": {"type": "string", "enum": ["init", "opt"]},
                    "agentMode": {
                        "type": "string",
                        "enum": ["chat", "react", "plan", "refine", "centralized", "decentralized", "init", "opt"],
                    },
                    "model": {"type": "string"},
                    "maxOutputTokens": {"type": "integer"},
                    "recent8History": {"type": "array"},
                    "workspaceCapability": {"type": "string"},
                    "workspaceBoundary": {"type": "string"},
                    "persistentMemorySummary": {"type": "array"},
                    "toolMetadata": {"type": "array"},
                    "inputAssets": {"type": "array"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="render_static_game_prompt",
                    description="Render a Responses API payload for a simple game generation request.",
                    input={
                        "userRequest": "Create a keyboard controlled star collection game.",
                        "createType": "init",
                        "agentMode": "react",
                        "model": "gpt-5.5",
                        "maxOutputTokens": 25000,
                    },
                )
            ],
            handler=_prompt_render,
            side_effects=[],
            requires=["prompt.template"],
        )
    )
    registry.register(
        ToolSpec(
            name="memory.summary_build",
            category="extendable",
            summary="Build a compact memory summary from JSON memory index entries.",
            input_schema={
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {"type": "object"},
                    }
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="summarize_project_tags",
                    description="Summarize project tags before rendering a generation prompt.",
                    input={
                        "entries": [
                            {"memoryType": "project_tag", "tags": ["arcade", "keyboard"], "summary": "Fast arcade game."},
                            {"memoryType": "user_preference", "tags": ["bright"], "summary": "User prefers bright colors."},
                        ]
                    },
                )
            ],
            handler=_memory_summarize,
            side_effects=[],
            requires=["json.memory"],
        )
    )
    registry.register(
        ToolSpec(
            name="run_log.preview_step",
            category="extendable",
            summary="Validate and preview a run-log step without persisting it.",
            input_schema={
                "type": "object",
                "required": ["runId", "stage"],
                "properties": {
                    "runId": {"type": "string"},
                    "stage": {"type": "string"},
                    "status": {"type": "string"},
                    "inputSummary": {"type": "string"},
                    "outputSummary": {"type": "string"},
                    "metrics": {"type": "object"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="preview_prompt_rendered_step",
                    description="Preview the JSON shape of a prompt_rendered run step.",
                    input={
                        "runId": "run-demo",
                        "stage": "prompt_rendered",
                        "status": "succeeded",
                        "inputSummary": "Prompt context prepared.",
                        "outputSummary": "Responses API payload rendered.",
                        "metrics": {"template": "create_game"},
                    },
                )
            ],
            handler=_run_log_preview,
            side_effects=[],
            requires=["json.run_log"],
        )
    )
    registry.register(
        ToolSpec(
            name="command.plan",
            category="extendable",
            summary="Normalize a command execution request without running it.",
            input_schema={
                "type": "object",
                "required": ["args"],
                "properties": {
                    "args": {"type": "array", "items": {"type": "string"}},
                    "cwd": {"type": "string"},
                    "timeoutSeconds": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="plan_agent_tool_test",
                    description="Plan the focused agent tool test command.",
                    input={
                        "args": [".venv\\Scripts\\python", "tests\\test_agent_tools.py"],
                        "cwd": "apps/api",
                        "timeoutSeconds": 60,
                    },
                )
            ],
            handler=_command_plan,
            side_effects=[],
            requires=["command.plan"],
        )
    )
    registry.register(
        ToolSpec(
            name="git.worktree_plan",
            category="extendable",
            summary="Plan an isolated git worktree for an agent run without creating it.",
            input_schema={
                "type": "object",
                "required": ["runId"],
                "properties": {
                    "runId": {"type": "string"},
                    "baseRef": {"type": "string"},
                    "branchName": {"type": "string"},
                    "path": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="plan_run_worktree",
                    description="Plan the worktree path and branch for a Create run.",
                    input={"runId": "run-demo", "baseRef": "HEAD"},
                )
            ],
            handler=_git_worktree_plan,
            side_effects=[],
            requires=["git.plan"],
        )
    )
    registry.register(
        ToolSpec(
            name="storage.object_key_plan",
            category="extendable",
            summary="Plan a MinIO object key for memory, run-log, or generated artifact storage.",
            input_schema={
                "type": "object",
                "required": ["purpose", "filename"],
                "properties": {
                    "purpose": {"type": "string", "enum": ["memory", "run-log", "artifact", "task-state"]},
                    "filename": {"type": "string"},
                    "userId": {"type": "string"},
                    "projectId": {"type": "string"},
                    "contentType": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="plan_task_state_object",
                    description="Plan where a TaskState snapshot would be stored in MinIO.",
                    input={
                        "purpose": "task-state",
                        "filename": "task-state.json",
                        "userId": "user-demo",
                        "projectId": "project-demo",
                        "contentType": "application/json",
                    },
                )
            ],
            handler=_storage_object_plan,
            side_effects=[],
            requires=["storage.plan"],
        )
    )
    registry.register(
        ToolSpec(
            name="database.query_plan",
            category="extendable",
            summary="Normalize a database query target and filters without executing SQL.",
            input_schema={
                "type": "object",
                "required": ["entity"],
                "properties": {
                    "entity": {"type": "string", "enum": ["game", "project", "run", "asset", "memory"]},
                    "operation": {"type": "string", "enum": ["select", "insert", "update"]},
                    "filters": {"type": "object"},
                    "limit": {"type": "integer"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="plan_recent_runs_query",
                    description="Plan a query for the latest runs of a project.",
                    input={
                        "entity": "run",
                        "operation": "select",
                        "filters": {"projectId": "project-demo", "userId": "user-demo"},
                        "limit": 10,
                    },
                )
            ],
            handler=_database_query_plan,
            side_effects=[],
            requires=["database.plan"],
        )
    )
    registry.register(
        ToolSpec(
            name="test.plan",
            category="extendable",
            summary="Map a named verification suite to the command that should run it.",
            input_schema={
                "type": "object",
                "required": ["suite"],
                "properties": {
                    "suite": {
                        "type": "string",
                        "enum": ["agent_tools", "prompt_templates", "workspace_isolation", "llm_service"],
                    },
                    "cwd": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="plan_prompt_template_test",
                    description="Plan the prompt template verification suite.",
                    input={"suite": "prompt_templates", "cwd": "apps/api"},
                )
            ],
            handler=_test_plan,
            side_effects=[],
            requires=["test.plan"],
        )
    )
    registry.register(
        ToolSpec(
            name="web.fetch_plan",
            category="extendable",
            summary="Validate the shape of a future web fetch request without network access.",
            input_schema={
                "type": "object",
                "required": ["url"],
                "properties": {
                    "url": {"type": "string"},
                    "method": {"type": "string", "enum": ["GET", "HEAD"]},
                    "purpose": {"type": "string"},
                },
                "additionalProperties": False,
            },
            output_schema=JSON_RESULT_SCHEMA,
            examples=[
                ToolExample(
                    name="plan_reference_fetch",
                    description="Plan a future fetch of a public reference page.",
                    input={"url": "https://www.astrocade.com/", "method": "GET", "purpose": "reference"},
                )
            ],
            handler=_web_fetch_plan,
            side_effects=[],
            requires=["web.plan"],
        )
    )
    return registry


def list_builtin_tool_metadata() -> list[dict[str, Any]]:
    return build_builtin_tool_registry().list_metadata()


def run_builtin_tool_examples() -> list[dict[str, Any]]:
    return build_builtin_tool_registry().run_examples()
