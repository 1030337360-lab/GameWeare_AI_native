from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.framework.workspace import WorkspaceContext, WorkspaceFS


def run() -> None:
    root = Path(__file__).resolve().parents[1]
    context = WorkspaceContext(
        run_id=str(uuid4()),
        project_id=str(uuid4()),
        workspace_root=str(root),
        worktree_stub_path=str(root / ".worktrees" / "create-test"),
        branch_name="codex/create-test",
        base_commit=None,
        cleanup_policy="manual",
        isolation_mode="stub",
        capability="read_write",
        status="prepared",
    )
    fs = WorkspaceFS(context)
    assert fs.list_files("app")

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


if __name__ == "__main__":
    run()
    print("workspace isolation checks passed")
