from pathlib import Path
import os
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from tests.support.integration import configure_test_environment, isolated_integration_test

configure_test_environment()

from app.config import get_settings
from app.database import db_connection
from app.agents.framework.schema import ensure_agent_framework_schema
from app.agents.framework.workspace import WorkspaceContext, WorkspaceFS, WorktreeManager


def run() -> None:
    root = Path(__file__).resolve().parents[1]
    stub_root = root / ".worktrees" / f"create-test-{uuid4().hex}"
    context = WorkspaceContext(
        run_id=str(uuid4()),
        project_id=str(uuid4()),
        workspace_root=str(root),
        worktree_stub_path=str(stub_root),
        branch_name="codex/create-test",
        base_commit=None,
        cleanup_policy="manual",
        isolation_mode="stub",
        capability="read_write",
        status="prepared",
    )
    fs = WorkspaceFS(context)
    assert fs.list_files(".") == []
    fs.write_text("index.html", "<html>stub</html>")
    assert fs.read_text("index.html") == "<html>stub</html>"
    assert not (root / "index.html").exists()

    try:
        fs.read_text(str(root / "app" / "main.py"))
    except PermissionError:
        pass
    else:
        raise AssertionError("absolute path must be rejected")

    try:
        fs.read_text("../outside.txt")
    except PermissionError:
        pass
    else:
        raise AssertionError("path traversal must be rejected")

    read_only = WorkspaceContext(
        **{
            **context.__dict__,
            "capability": "read_only",
        }
    )
    try:
        WorkspaceFS(read_only).write_text("tmp/blocked.txt", "blocked")
    except PermissionError:
        pass
    else:
        raise AssertionError("read_only workspace must reject writes")

    isolated_root = root / ".worktrees" / f"create-{uuid4().hex}"
    isolated = WorkspaceContext(**{**context.__dict__, "worktree_stub_path": str(isolated_root)})
    isolated_fs = WorkspaceFS(isolated)
    isolated_fs.write_text("index.html", "<html>isolated</html>")
    assert (isolated_root / "index.html").read_text(encoding="utf-8") == "<html>isolated</html>"
    assert not (root / "index.html").exists()

    if os.environ.get("RUN_GIT_WORKTREE_TEST") == "1":
        previous = {
            "CREATE_WORKTREE_ENABLED": os.environ.get("CREATE_WORKTREE_ENABLED"),
            "CREATE_WORKTREE_CLEANUP_POLICY": os.environ.get("CREATE_WORKTREE_CLEANUP_POLICY"),
        }
        os.environ["CREATE_WORKTREE_ENABLED"] = "true"
        os.environ["CREATE_WORKTREE_CLEANUP_POLICY"] = "auto_on_success"
        get_settings.cache_clear()
        run_id = str(uuid4())
        ensure_agent_framework_schema()
        with db_connection() as connection:
            user = connection.execute(
                """
INSERT INTO users (email, display_name)
VALUES (%s, 'Workspace Test User')
RETURNING id
""",
                (f"workspace-{uuid4().hex}@gameweare.local",),
            ).fetchone()
            project = connection.execute(
                """
INSERT INTO agent_projects (user_id, title, status)
VALUES (%s, 'Workspace Test Project', 'active')
RETURNING id
""",
                (user["id"],),
            ).fetchone()
            connection.execute(
                """
INSERT INTO create_runs (id, task_id, project_id, user_id, create_type, agent_mode, status, log_object_key)
VALUES (%s, gen_random_uuid(), %s, %s, 'init', 'react', 'running', %s)
""",
                (run_id, project["id"], user["id"], f"agent-runs/{run_id}/run-log.jsonl"),
            )
        context = None
        try:
            context = WorktreeManager().prepare(run_id=run_id, project_id=str(project["id"]))
            assert context.isolation_mode == "git_worktree"
            assert context.base_commit
            assert Path(context.worktree_stub_path).exists()
            WorkspaceFS(context).write_text("index.html", "<html>worktree</html>")
            assert not (root / "index.html").exists()
        finally:
            WorktreeManager().cleanup(run_id)
            for key, value in previous.items():
                if value is None:
                    os.environ.pop(key, None)
                else:
                    os.environ[key] = value
            get_settings.cache_clear()


if __name__ == "__main__":
    with isolated_integration_test():
        run()
    print("workspace isolation checks passed")
