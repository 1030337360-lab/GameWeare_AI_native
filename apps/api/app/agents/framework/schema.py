from __future__ import annotations

from app.database import db_connection

_SCHEMA_READY = False


def ensure_agent_framework_schema() -> None:
    global _SCHEMA_READY
    if _SCHEMA_READY:
        return

    with db_connection() as connection:
        connection.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")
        connection.execute(
            """
CREATE TABLE IF NOT EXISTS agent_projects (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game_id uuid REFERENCES games(id) ON DELETE SET NULL,
  title varchar(160) NOT NULL DEFAULT 'Untitled project',
  status varchar(30) NOT NULL DEFAULT 'active',
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_projects_status_check CHECK (status IN ('active', 'archived', 'deleted'))
)
"""
        )
        connection.execute(
            """
CREATE TABLE IF NOT EXISTS create_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  task_id uuid NOT NULL,
  project_id uuid NOT NULL REFERENCES agent_projects(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  job_id uuid REFERENCES generation_jobs(id) ON DELETE SET NULL,
  game_id uuid REFERENCES games(id) ON DELETE SET NULL,
  version_id uuid REFERENCES game_versions(id) ON DELETE SET NULL,
  create_type varchar(20) NOT NULL,
  agent_mode varchar(20) NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'running',
  summary jsonb NOT NULL DEFAULT '{}'::jsonb,
  log_object_key text NOT NULL,
  started_at timestamptz NOT NULL DEFAULT now(),
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT create_runs_create_type_check CHECK (create_type IN ('init', 'opt')),
  CONSTRAINT create_runs_agent_mode_check CHECK (agent_mode IN ('chat', 'react', 'plan', 'refine', 'decentralized', 'init', 'opt')),
  CONSTRAINT create_runs_status_check CHECK (status IN ('running', 'completed', 'failed', 'canceled'))
)
"""
        )
        connection.execute(
            """
CREATE TABLE IF NOT EXISTS create_run_steps (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  run_id uuid NOT NULL REFERENCES create_runs(id) ON DELETE CASCADE,
  step_no int NOT NULL,
  stage varchar(60) NOT NULL,
  status varchar(30) NOT NULL,
  input_summary text,
  output_summary text,
  metrics jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (run_id, step_no),
  CONSTRAINT create_run_steps_status_check CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped'))
)
"""
        )
        connection.execute(
            """
CREATE TABLE IF NOT EXISTS agent_memory_index (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES agent_projects(id) ON DELETE CASCADE,
  memory_type varchar(40) NOT NULL,
  tags text[] NOT NULL DEFAULT ARRAY[]::text[],
  bucket varchar(100) NOT NULL,
  object_key text NOT NULL,
  sha256 char(64) NOT NULL,
  summary text,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_memory_index_type_check CHECK (memory_type IN ('user_preference', 'project_tag', 'upload_index', 'custom_skill', 'task_state', 'run_log')),
  UNIQUE (bucket, object_key)
)
"""
        )
        connection.execute(
            """
CREATE TABLE IF NOT EXISTS agent_task_state_index (
  run_id uuid PRIMARY KEY REFERENCES create_runs(id) ON DELETE CASCADE,
  task_id uuid NOT NULL,
  project_id uuid NOT NULL REFERENCES agent_projects(id) ON DELETE CASCADE,
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  status varchar(30) NOT NULL,
  checkpoint_object_key text NOT NULL,
  latest_log_object_key text NOT NULL,
  resume_status varchar(40) NOT NULL DEFAULT 'fresh',
  updated_at timestamptz NOT NULL DEFAULT now()
)
"""
        )
        connection.execute(
            """
CREATE TABLE IF NOT EXISTS agent_workspace_runs (
  run_id uuid PRIMARY KEY REFERENCES create_runs(id) ON DELETE CASCADE,
  project_id uuid NOT NULL REFERENCES agent_projects(id) ON DELETE CASCADE,
  workspace_root text NOT NULL,
  worktree_stub_path text NOT NULL,
  branch_name text,
  base_commit text,
  cleanup_policy varchar(30) NOT NULL DEFAULT 'manual',
  isolation_mode varchar(30) NOT NULL DEFAULT 'stub',
  capability varchar(30) NOT NULL,
  status varchar(30) NOT NULL DEFAULT 'prepared',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_workspace_cleanup_policy_check CHECK (cleanup_policy IN ('manual', 'auto', 'auto_on_success', 'auto_always')),
  CONSTRAINT agent_workspace_isolation_mode_check CHECK (isolation_mode IN ('stub', 'git_worktree')),
  CONSTRAINT agent_workspace_capability_check CHECK (capability IN ('read_only', 'write_only', 'read_write', 'web_only')),
  CONSTRAINT agent_workspace_status_check CHECK (status IN ('planned', 'prepared', 'running', 'completed', 'failed', 'cleaned'))
)
"""
        )
        connection.execute("ALTER TABLE create_runs DROP CONSTRAINT IF EXISTS create_runs_agent_mode_check")
        connection.execute("UPDATE create_runs SET agent_mode = 'decentralized' WHERE agent_mode = 'centralized'")
        connection.execute(
            """
ALTER TABLE create_runs
ADD CONSTRAINT create_runs_agent_mode_check
CHECK (agent_mode IN ('chat', 'react', 'plan', 'refine', 'decentralized', 'init', 'opt'))
"""
        )
        connection.execute("ALTER TABLE agent_workspace_runs ADD COLUMN IF NOT EXISTS branch_name text")
        connection.execute("ALTER TABLE agent_workspace_runs ADD COLUMN IF NOT EXISTS base_commit text")
        connection.execute("ALTER TABLE agent_workspace_runs ADD COLUMN IF NOT EXISTS cleanup_policy varchar(30) NOT NULL DEFAULT 'manual'")
        connection.execute("ALTER TABLE agent_workspace_runs ADD COLUMN IF NOT EXISTS isolation_mode varchar(30) NOT NULL DEFAULT 'stub'")
        connection.execute("ALTER TABLE agent_workspace_runs DROP CONSTRAINT IF EXISTS agent_workspace_cleanup_policy_check")
        connection.execute(
            """
ALTER TABLE agent_workspace_runs
ADD CONSTRAINT agent_workspace_cleanup_policy_check
CHECK (cleanup_policy IN ('manual', 'auto', 'auto_on_success', 'auto_always'))
"""
        )
        connection.execute("CREATE INDEX IF NOT EXISTS ix_agent_projects_user_updated ON agent_projects(user_id, updated_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_create_runs_project_created ON create_runs(project_id, created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_create_runs_user_created ON create_runs(user_id, created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_create_run_steps_run_step ON create_run_steps(run_id, step_no)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_agent_memory_project_type ON agent_memory_index(project_id, memory_type, created_at DESC)")
        connection.execute("CREATE INDEX IF NOT EXISTS ix_agent_memory_tags ON agent_memory_index USING gin(tags)")
        connection.execute(
            """
DO $$
BEGIN
  IF EXISTS (
    SELECT 1 FROM pg_proc p
    JOIN pg_namespace n ON n.oid = p.pronamespace
    WHERE p.proname = 'set_updated_at' AND n.nspname = 'public'
  ) THEN
    DROP TRIGGER IF EXISTS set_agent_projects_updated_at ON agent_projects;
    CREATE TRIGGER set_agent_projects_updated_at
      BEFORE UPDATE ON agent_projects
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();

    DROP TRIGGER IF EXISTS set_create_runs_updated_at ON create_runs;
    CREATE TRIGGER set_create_runs_updated_at
      BEFORE UPDATE ON create_runs
      FOR EACH ROW EXECUTE FUNCTION set_updated_at();
  END IF;
END $$;
"""
        )

    _SCHEMA_READY = True
