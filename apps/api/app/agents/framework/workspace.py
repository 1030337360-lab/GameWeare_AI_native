from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from collections.abc import Sequence

from app.config import get_settings
from app.database import db_connection


@dataclass(frozen=True)
class WorkspaceContext:
    run_id: str
    project_id: str
    workspace_root: str
    worktree_stub_path: str
    branch_name: str | None
    base_commit: str | None
    cleanup_policy: str
    isolation_mode: str
    capability: str
    status: str


class WorktreeManager:
    def __init__(self, capability: str = "read_write"):
        self.capability = capability

    def _repo_root(self) -> Path:
        return Path(__file__).resolve().parents[5]

    def _git(self, args: list[str], cwd: Path) -> str:
        completed = subprocess.run(
            ["git", *args],
            cwd=cwd,
            shell=False,
            check=True,
            capture_output=True,
            text=True,
            timeout=30,
        )
        return completed.stdout.strip()

    def prepare(self, *, run_id: str, project_id: str) -> WorkspaceContext:
        settings = get_settings()
        repo_root = self._repo_root()
        worktree_stub_path = repo_root / ".worktrees" / f"create-{run_id}"
        branch_name = f"codex/create-{run_id}"
        base_commit = None
        isolation_mode = "stub"
        status = "prepared"

        if settings.create_worktree_enabled:
            base_commit = self._git(["rev-parse", settings.create_worktree_base_ref], repo_root)
            worktree_stub_path.parent.mkdir(parents=True, exist_ok=True)
            self._git(
                [
                    "worktree",
                    "add",
                    str(worktree_stub_path),
                    "-b",
                    branch_name,
                    settings.create_worktree_base_ref,
                ],
                repo_root,
            )
            isolation_mode = "git_worktree"

        context = WorkspaceContext(
            run_id=run_id,
            project_id=project_id,
            workspace_root=str(repo_root),
            worktree_stub_path=str(worktree_stub_path),
            branch_name=branch_name,
            base_commit=base_commit,
            cleanup_policy=settings.create_worktree_cleanup_policy,
            isolation_mode=isolation_mode,
            capability=self.capability,
            status=status,
        )
        with db_connection() as connection:
            connection.execute(
                """
INSERT INTO agent_workspace_runs (
  run_id,
  project_id,
  workspace_root,
  worktree_stub_path,
  branch_name,
  base_commit,
  cleanup_policy,
  isolation_mode,
  capability,
  status
)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (run_id) DO UPDATE SET
  workspace_root = EXCLUDED.workspace_root,
  worktree_stub_path = EXCLUDED.worktree_stub_path,
  branch_name = EXCLUDED.branch_name,
  base_commit = EXCLUDED.base_commit,
  cleanup_policy = EXCLUDED.cleanup_policy,
  isolation_mode = EXCLUDED.isolation_mode,
  capability = EXCLUDED.capability,
  status = EXCLUDED.status,
  updated_at = now()
""",
                (
                    run_id,
                    project_id,
                    context.workspace_root,
                    context.worktree_stub_path,
                    context.branch_name,
                    context.base_commit,
                    context.cleanup_policy,
                    context.isolation_mode,
                    context.capability,
                    context.status,
                ),
            )
        return context

    def status(self, run_id: str) -> dict[str, str] | None:
        with db_connection() as connection:
            row = connection.execute(
                """
SELECT
  workspace_root,
  worktree_stub_path,
  branch_name,
  base_commit,
  cleanup_policy,
  isolation_mode,
  capability,
  status
FROM agent_workspace_runs
WHERE run_id = %s
LIMIT 1
""",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        return {
            "workspaceRoot": row["workspace_root"],
            "worktreeStubPath": row["worktree_stub_path"],
            "branchName": row["branch_name"],
            "baseCommit": row["base_commit"],
            "cleanupPolicy": row["cleanup_policy"],
            "isolationMode": row["isolation_mode"],
            "capability": row["capability"],
            "status": row["status"],
        }

    def cleanup(self, run_id: str) -> None:
        row = self.status(run_id)
        if row and row["isolationMode"] == "git_worktree":
            repo_root = Path(row["workspaceRoot"])
            worktree_path = Path(row["worktreeStubPath"])
            if worktree_path.exists():
                self._git(["worktree", "remove", str(worktree_path), "--force"], repo_root)
            branch_name = row.get("branchName")
            if branch_name:
                try:
                    self._git(["branch", "-D", branch_name], repo_root)
                except subprocess.CalledProcessError:
                    pass
            self._git(["worktree", "prune"], repo_root)
        elif row and row["isolationMode"] == "stub":
            worktree_path = Path(row["worktreeStubPath"])
            if worktree_path.exists() and worktree_path.name.startswith("create-"):
                shutil.rmtree(worktree_path)
        with db_connection() as connection:
            connection.execute(
                "UPDATE agent_workspace_runs SET status = 'cleaned', updated_at = now() WHERE run_id = %s",
                (run_id,),
            )


class WorkspaceFS:
    def __init__(self, context: WorkspaceContext):
        self.context = context
        stub_root = Path(context.worktree_stub_path).resolve()
        self.stub_root = stub_root
        self.uses_isolated_root = context.isolation_mode == "git_worktree" or stub_root.exists()
        if context.isolation_mode == "git_worktree" or stub_root.exists():
            self.root = stub_root
        else:
            self.root = Path(context.workspace_root).resolve()

    def _resolve(self, relative_path: str) -> Path:
        candidate = Path(relative_path)
        if candidate.is_absolute():
            raise PermissionError("Workspace paths must be relative.")
        target = (self.root / candidate).resolve()
        if target != self.root and self.root not in target.parents:
            raise PermissionError("Path escapes the workspace boundary.")
        if target.exists() and target.is_symlink():
            resolved = target.resolve()
            if resolved != self.root and self.root not in resolved.parents:
                raise PermissionError("Symlink target escapes the workspace boundary.")
        return target

    def _assert_can_read(self) -> None:
        if self.context.capability not in {"read_only", "read_write"}:
            raise PermissionError("Workspace capability does not allow reading.")

    def _assert_can_write(self) -> None:
        if self.context.isolation_mode == "git_worktree":
            pass
        elif self.context.isolation_mode == "stub" and self.uses_isolated_root and self.root == self.stub_root:
            pass
        else:
            raise PermissionError("Writes require an isolated workspace mode.")
        if self.context.capability not in {"write_only", "read_write"}:
            raise PermissionError("Workspace capability does not allow writing.")

    def read_text(self, relative_path: str, encoding: str = "utf-8") -> str:
        self._assert_can_read()
        return self._resolve(relative_path).read_text(encoding=encoding)

    def write_text(self, relative_path: str, content: str, encoding: str = "utf-8") -> None:
        self._assert_can_write()
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(content, encoding=encoding)

    def list_files(self, relative_path: str = ".") -> list[str]:
        self._assert_can_read()
        root = self._resolve(relative_path)
        if not root.exists():
            return []
        if root.is_file():
            return [str(root.relative_to(self.root))]
        return [str(path.relative_to(self.root)) for path in root.rglob("*") if path.is_file()]


class WorkspaceCommandRunner:
    def __init__(self, context: WorkspaceContext):
        self.context = context
        self.fs = WorkspaceFS(context)

    def run(
        self,
        args: Sequence[str],
        *,
        cwd: str = ".",
        timeout_seconds: int = 60,
    ) -> dict[str, str | int]:
        if self.context.capability not in {"read_write", "read_only"}:
            raise PermissionError("Workspace capability does not allow command execution.")
        if not args:
            raise ValueError("Command args are required.")
        resolved_cwd = self.fs._resolve(cwd)
        completed = subprocess.run(
            list(args),
            cwd=resolved_cwd,
            shell=False,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
        )
        return {
            "returnCode": completed.returncode,
            "stdout": completed.stdout,
            "stderr": completed.stderr,
        }
