CREATE EXTENSION IF NOT EXISTS pgcrypto;
CREATE EXTENSION IF NOT EXISTS citext;

CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS trigger AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TABLE IF NOT EXISTS users (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  email citext UNIQUE,
  display_name varchar(80) NOT NULL,
  avatar_url text,
  bio text,
  role varchar(20) NOT NULL DEFAULT 'user',
  status varchar(20) NOT NULL DEFAULT 'active',
  last_login_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT users_role_check CHECK (role IN ('user', 'admin')),
  CONSTRAINT users_status_check CHECK (status IN ('active', 'disabled', 'deleted'))
);

CREATE TABLE IF NOT EXISTS auth_accounts (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  provider varchar(40) NOT NULL,
  provider_user_id text,
  provider_email citext,
  password_hash text,
  access_token_encrypted text,
  refresh_token_encrypted text,
  expires_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT auth_accounts_provider_check CHECK (provider IN ('email', 'google', 'github'))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_auth_accounts_provider_user_id
  ON auth_accounts(provider, provider_user_id)
  WHERE provider_user_id IS NOT NULL;

CREATE UNIQUE INDEX IF NOT EXISTS ux_auth_accounts_provider_email
  ON auth_accounts(provider, provider_email)
  WHERE provider_email IS NOT NULL;

CREATE TABLE IF NOT EXISTS user_sessions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  session_token_hash text NOT NULL UNIQUE,
  user_agent text,
  ip_address inet,
  expires_at timestamptz NOT NULL,
  revoked_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id_created_at
  ON user_sessions(user_id, created_at DESC);

CREATE TABLE IF NOT EXISTS games (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  slug varchar(120) NOT NULL UNIQUE,
  author_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  title varchar(120) NOT NULL,
  description text NOT NULL DEFAULT '',
  cover_asset_id uuid,
  visibility varchar(20) NOT NULL DEFAULT 'private',
  publish_status varchar(20) NOT NULL DEFAULT 'draft',
  current_version_id uuid,
  plays_count bigint NOT NULL DEFAULT 0,
  likes_count bigint NOT NULL DEFAULT 0,
  favorites_count bigint NOT NULL DEFAULT 0,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  published_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT games_visibility_check CHECK (visibility IN ('private', 'unlisted', 'public')),
  CONSTRAINT games_publish_status_check CHECK (publish_status IN ('draft', 'reviewing', 'published', 'rejected', 'archived')),
  CONSTRAINT games_counts_check CHECK (plays_count >= 0 AND likes_count >= 0 AND favorites_count >= 0)
);

CREATE TABLE IF NOT EXISTS tags (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  name varchar(60) NOT NULL UNIQUE,
  created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS game_tags (
  game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  tag_id uuid NOT NULL REFERENCES tags(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (game_id, tag_id)
);

CREATE TABLE IF NOT EXISTS generation_jobs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  creator_id uuid NOT NULL REFERENCES users(id) ON DELETE RESTRICT,
  game_id uuid REFERENCES games(id) ON DELETE SET NULL,
  version_id uuid,
  prompt text NOT NULL DEFAULT '',
  input_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
  status varchar(30) NOT NULL DEFAULT 'pending',
  current_stage varchar(40),
  error_code varchar(80),
  error_message text,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT generation_jobs_status_check CHECK (status IN ('pending', 'planning', 'generating', 'building', 'reviewing', 'uploading', 'completed', 'failed', 'canceled'))
);

CREATE TABLE IF NOT EXISTS game_versions (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  version_no int NOT NULL,
  source_job_id uuid REFERENCES generation_jobs(id) ON DELETE SET NULL,
  runtime varchar(40) NOT NULL DEFAULT 'iframe-html5',
  manifest_asset_id uuid,
  entry_file varchar(255) NOT NULL DEFAULT 'index.html',
  build_status varchar(20) NOT NULL DEFAULT 'pending',
  safety_status varchar(20) NOT NULL DEFAULT 'pending',
  storage_prefix text NOT NULL,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT game_versions_version_no_check CHECK (version_no > 0),
  CONSTRAINT game_versions_build_status_check CHECK (build_status IN ('pending', 'building', 'succeeded', 'failed')),
  CONSTRAINT game_versions_safety_status_check CHECK (safety_status IN ('pending', 'passed', 'failed')),
  UNIQUE (game_id, version_no)
);

CREATE TABLE IF NOT EXISTS assets (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  owner_id uuid REFERENCES users(id) ON DELETE SET NULL,
  game_id uuid REFERENCES games(id) ON DELETE SET NULL,
  version_id uuid REFERENCES game_versions(id) ON DELETE SET NULL,
  job_id uuid REFERENCES generation_jobs(id) ON DELETE SET NULL,
  kind varchar(30) NOT NULL,
  bucket varchar(100) NOT NULL,
  object_key text NOT NULL,
  public_url text,
  content_type varchar(120) NOT NULL DEFAULT 'application/octet-stream',
  size_bytes bigint NOT NULL DEFAULT 0,
  sha256 char(64),
  width int,
  height int,
  duration_ms int,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT assets_kind_check CHECK (kind IN ('upload', 'cover', 'manifest', 'bundle', 'source', 'generated')),
  CONSTRAINT assets_size_check CHECK (size_bytes >= 0),
  CONSTRAINT assets_width_check CHECK (width IS NULL OR width > 0),
  CONSTRAINT assets_height_check CHECK (height IS NULL OR height > 0),
  CONSTRAINT assets_duration_check CHECK (duration_ms IS NULL OR duration_ms >= 0),
  UNIQUE (bucket, object_key)
);

CREATE TABLE IF NOT EXISTS agent_runs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
  stage varchar(40) NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'pending',
  input_summary text,
  output_summary text,
  log jsonb NOT NULL DEFAULT '{}'::jsonb,
  started_at timestamptz,
  completed_at timestamptz,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT agent_runs_stage_check CHECK (stage IN ('planner', 'asset', 'game_code', 'build', 'safety', 'publisher', 'create')),
  CONSTRAINT agent_runs_status_check CHECK (status IN ('pending', 'running', 'succeeded', 'failed', 'skipped'))
);

CREATE TABLE IF NOT EXISTS job_artifacts (
  job_id uuid NOT NULL REFERENCES generation_jobs(id) ON DELETE CASCADE,
  asset_id uuid NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
  purpose varchar(40) NOT NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (job_id, asset_id, purpose),
  CONSTRAINT job_artifacts_purpose_check CHECK (purpose IN ('input', 'generated', 'manifest', 'preview', 'final'))
);

CREATE TABLE IF NOT EXISTS play_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  anonymous_id uuid,
  game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  version_id uuid REFERENCES game_versions(id) ON DELETE SET NULL,
  event_type varchar(40) NOT NULL,
  duration_ms int,
  error_message text,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT play_events_event_type_check CHECK (event_type IN ('game_view', 'game_start', 'game_load_error', 'game_end')),
  CONSTRAINT play_events_duration_check CHECK (duration_ms IS NULL OR duration_ms >= 0)
);

CREATE TABLE IF NOT EXISTS game_likes (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, game_id)
);

CREATE TABLE IF NOT EXISTS game_favorites (
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  created_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (user_id, game_id)
);

CREATE TABLE IF NOT EXISTS game_comments (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  game_id uuid NOT NULL REFERENCES games(id) ON DELETE CASCADE,
  body text NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'visible',
  created_at timestamptz NOT NULL DEFAULT now(),
  deleted_at timestamptz,
  CONSTRAINT game_comments_status_check CHECK (status IN ('visible', 'hidden', 'deleted'))
);

CREATE TABLE IF NOT EXISTS moderation_reviews (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  target_type varchar(30) NOT NULL,
  target_id uuid NOT NULL,
  status varchar(20) NOT NULL DEFAULT 'pending',
  reason text,
  reviewer_id uuid REFERENCES users(id) ON DELETE SET NULL,
  created_at timestamptz NOT NULL DEFAULT now(),
  reviewed_at timestamptz,
  CONSTRAINT moderation_reviews_target_type_check CHECK (target_type IN ('game', 'version', 'asset', 'job', 'comment')),
  CONSTRAINT moderation_reviews_status_check CHECK (status IN ('pending', 'approved', 'rejected'))
);

CREATE TABLE IF NOT EXISTS model_usage_events (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  job_id uuid REFERENCES generation_jobs(id) ON DELETE SET NULL,
  agent_run_id uuid REFERENCES agent_runs(id) ON DELETE SET NULL,
  provider varchar(80) NOT NULL,
  model varchar(120) NOT NULL,
  prompt_tokens int NOT NULL DEFAULT 0,
  completion_tokens int NOT NULL DEFAULT 0,
  total_tokens int NOT NULL DEFAULT 0,
  cost_usd numeric(12,6),
  latency_ms int,
  created_at timestamptz NOT NULL DEFAULT now(),
  CONSTRAINT model_usage_tokens_check CHECK (prompt_tokens >= 0 AND completion_tokens >= 0 AND total_tokens >= 0),
  CONSTRAINT model_usage_latency_check CHECK (latency_ms IS NULL OR latency_ms >= 0)
);

CREATE TABLE IF NOT EXISTS audit_logs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  actor_user_id uuid REFERENCES users(id) ON DELETE SET NULL,
  action varchar(80) NOT NULL,
  target_type varchar(40) NOT NULL,
  target_id uuid,
  metadata jsonb NOT NULL DEFAULT '{}'::jsonb,
  created_at timestamptz NOT NULL DEFAULT now()
);

DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_games_cover_asset') THEN
    ALTER TABLE games
      ADD CONSTRAINT fk_games_cover_asset
      FOREIGN KEY (cover_asset_id) REFERENCES assets(id) ON DELETE SET NULL
      DEFERRABLE INITIALLY DEFERRED;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_games_current_version') THEN
    ALTER TABLE games
      ADD CONSTRAINT fk_games_current_version
      FOREIGN KEY (current_version_id) REFERENCES game_versions(id) ON DELETE SET NULL
      DEFERRABLE INITIALLY DEFERRED;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_game_versions_manifest_asset') THEN
    ALTER TABLE game_versions
      ADD CONSTRAINT fk_game_versions_manifest_asset
      FOREIGN KEY (manifest_asset_id) REFERENCES assets(id) ON DELETE SET NULL
      DEFERRABLE INITIALLY DEFERRED;
  END IF;

  IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = 'fk_generation_jobs_version') THEN
    ALTER TABLE generation_jobs
      ADD CONSTRAINT fk_generation_jobs_version
      FOREIGN KEY (version_id) REFERENCES game_versions(id) ON DELETE SET NULL
      DEFERRABLE INITIALLY DEFERRED;
  END IF;
END $$;

CREATE INDEX IF NOT EXISTS ix_games_public_listing
  ON games(publish_status, visibility, published_at DESC);

CREATE INDEX IF NOT EXISTS ix_games_author_created_at
  ON games(author_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_game_versions_game_version
  ON game_versions(game_id, version_no DESC);

CREATE INDEX IF NOT EXISTS ix_generation_jobs_creator_created_at
  ON generation_jobs(creator_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_generation_jobs_status_created_at
  ON generation_jobs(status, created_at);

CREATE INDEX IF NOT EXISTS ix_agent_runs_job_created_at
  ON agent_runs(job_id, created_at);

CREATE INDEX IF NOT EXISTS ix_assets_job_created_at
  ON assets(job_id, created_at);

CREATE INDEX IF NOT EXISTS ix_assets_game_version
  ON assets(game_id, version_id);

CREATE INDEX IF NOT EXISTS ix_play_events_game_created_at
  ON play_events(game_id, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_play_events_user_daily
  ON play_events(game_id, user_id, event_type, created_at DESC)
  WHERE user_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_play_events_anonymous_daily
  ON play_events(game_id, anonymous_id, event_type, created_at DESC)
  WHERE anonymous_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_game_tags_tag_game
  ON game_tags(tag_id, game_id);

CREATE INDEX IF NOT EXISTS ix_games_search
  ON games USING gin(to_tsvector('simple', coalesce(title, '') || ' ' || coalesce(description, '')));

DROP TRIGGER IF EXISTS set_users_updated_at ON users;
CREATE TRIGGER set_users_updated_at
  BEFORE UPDATE ON users
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_auth_accounts_updated_at ON auth_accounts;
CREATE TRIGGER set_auth_accounts_updated_at
  BEFORE UPDATE ON auth_accounts
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_games_updated_at ON games;
CREATE TRIGGER set_games_updated_at
  BEFORE UPDATE ON games
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS set_generation_jobs_updated_at ON generation_jobs;
CREATE TRIGGER set_generation_jobs_updated_at
  BEFORE UPDATE ON generation_jobs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
