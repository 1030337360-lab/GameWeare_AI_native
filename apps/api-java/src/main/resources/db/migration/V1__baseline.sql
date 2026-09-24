CREATE TABLE users (
  id VARCHAR(36) PRIMARY KEY,
  email VARCHAR(254) NOT NULL UNIQUE,
  password_hash VARCHAR(255) NOT NULL,
  display_name VARCHAR(120) NOT NULL,
  avatar_url VARCHAR(1024),
  role VARCHAR(30) NOT NULL DEFAULT 'user',
  last_login_at DATETIME(6),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE user_sessions (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  token_hash CHAR(64) NOT NULL UNIQUE,
  expires_at DATETIME(6) NOT NULL,
  revoked_at DATETIME(6),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX ix_sessions_user (user_id, expires_at),
  CONSTRAINT fk_sessions_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE token_accounts (
  user_id VARCHAR(36) PRIMARY KEY,
  balance BIGINT NOT NULL DEFAULT 0,
  reserved BIGINT NOT NULL DEFAULT 0,
  version BIGINT NOT NULL DEFAULT 0,
  CONSTRAINT fk_token_account_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT ck_token_account_nonnegative CHECK (balance >= 0 AND reserved >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE token_ledger (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  job_id VARCHAR(36) NOT NULL,
  entry_type VARCHAR(20) NOT NULL,
  amount BIGINT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_ledger_job_type (job_id, entry_type),
  INDEX ix_ledger_user_created (user_id, created_at),
  CONSTRAINT fk_ledger_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT ck_ledger_amount CHECK (amount >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE tags (
  id VARCHAR(36) PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE games (
  id VARCHAR(36) PRIMARY KEY,
  slug VARCHAR(160) NOT NULL UNIQUE,
  title VARCHAR(255) NOT NULL,
  description TEXT,
  author_id VARCHAR(36) NOT NULL,
  publish_status VARCHAR(30) NOT NULL DEFAULT 'draft',
  visibility VARCHAR(30) NOT NULL DEFAULT 'private',
  current_version_id VARCHAR(36),
  cover_object_key VARCHAR(1024),
  plays_count BIGINT NOT NULL DEFAULT 0,
  likes_count BIGINT NOT NULL DEFAULT 0,
  favorites_count BIGINT NOT NULL DEFAULT 0,
  published_at DATETIME(6),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  INDEX ix_games_listing (publish_status, visibility, published_at),
  INDEX ix_games_author (author_id, created_at),
  CONSTRAINT fk_games_author FOREIGN KEY (author_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE game_tags (
  game_id VARCHAR(36) NOT NULL,
  tag_id VARCHAR(36) NOT NULL,
  PRIMARY KEY (game_id, tag_id),
  CONSTRAINT fk_game_tags_game FOREIGN KEY (game_id) REFERENCES games(id),
  CONSTRAINT fk_game_tags_tag FOREIGN KEY (tag_id) REFERENCES tags(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE create_projects (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  title VARCHAR(255) NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'active',
  game_id VARCHAR(36),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  INDEX ix_projects_user (user_id, updated_at),
  CONSTRAINT fk_projects_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_projects_game FOREIGN KEY (game_id) REFERENCES games(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE create_jobs (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  project_id VARCHAR(36) NOT NULL,
  prompt LONGTEXT NOT NULL,
  agent_mode VARCHAR(30) NOT NULL,
  create_type VARCHAR(20) NOT NULL,
  status VARCHAR(30) NOT NULL DEFAULT 'pending',
  error_message TEXT,
  game_id VARCHAR(36),
  version_id VARCHAR(36),
  idempotency_key VARCHAR(120),
  reserved_tokens BIGINT NOT NULL DEFAULT 0,
  actual_tokens BIGINT,
  lease_token VARCHAR(36),
  lease_expires_at DATETIME(6),
  attempts INT NOT NULL DEFAULT 0,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_jobs_idempotency (user_id, idempotency_key),
  INDEX ix_jobs_status (status, created_at),
  INDEX ix_jobs_project (project_id, created_at),
  CONSTRAINT fk_jobs_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_jobs_project FOREIGN KEY (project_id) REFERENCES create_projects(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE game_versions (
  id VARCHAR(36) PRIMARY KEY,
  game_id VARCHAR(36) NOT NULL,
  version_no INT NOT NULL,
  entry_object_key VARCHAR(1024) NOT NULL,
  manifest_object_key VARCHAR(1024),
  runtime VARCHAR(40) NOT NULL DEFAULT 'iframe-html5',
  build_status VARCHAR(30) NOT NULL DEFAULT 'passed',
  safety_status VARCHAR(30) NOT NULL DEFAULT 'passed',
  entry_file VARCHAR(255) NOT NULL DEFAULT 'index.html',
  storage_prefix VARCHAR(1024),
  source_job_id VARCHAR(36),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_versions_game_no (game_id, version_no),
  CONSTRAINT fk_versions_game FOREIGN KEY (game_id) REFERENCES games(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE assets (
  id VARCHAR(36) PRIMARY KEY,
  owner_id VARCHAR(36),
  game_id VARCHAR(36),
  version_id VARCHAR(36),
  job_id VARCHAR(36),
  kind VARCHAR(30) NOT NULL,
  bucket VARCHAR(255) NOT NULL,
  object_key VARCHAR(512) NOT NULL,
  public_url VARCHAR(2048),
  content_type VARCHAR(255) NOT NULL,
  size_bytes BIGINT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_assets_object (bucket, object_key),
  INDEX ix_assets_owner (owner_id, created_at),
  CONSTRAINT fk_assets_owner FOREIGN KEY (owner_id) REFERENCES users(id),
  CONSTRAINT fk_assets_game FOREIGN KEY (game_id) REFERENCES games(id),
  CONSTRAINT fk_assets_version FOREIGN KEY (version_id) REFERENCES game_versions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE game_likes (
  user_id VARCHAR(36) NOT NULL,
  game_id VARCHAR(36) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id, game_id),
  CONSTRAINT fk_likes_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_likes_game FOREIGN KEY (game_id) REFERENCES games(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE game_favorites (
  user_id VARCHAR(36) NOT NULL,
  game_id VARCHAR(36) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id, game_id),
  CONSTRAINT fk_favorites_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_favorites_game FOREIGN KEY (game_id) REFERENCES games(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE play_events (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36),
  anonymous_id VARCHAR(64),
  game_id VARCHAR(36) NOT NULL,
  event_type VARCHAR(40) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX ix_play_events_game (game_id, created_at),
  INDEX ix_play_events_dedupe (game_id, user_id, anonymous_id, event_type, created_at),
  CONSTRAINT fk_play_events_game FOREIGN KEY (game_id) REFERENCES games(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE play_count_dedupe (
  game_id VARCHAR(36) NOT NULL,
  identity_key VARCHAR(130) NOT NULL,
  window_start DATETIME(6) NOT NULL,
  PRIMARY KEY (game_id, identity_key, window_start),
  CONSTRAINT fk_play_dedupe_game FOREIGN KEY (game_id) REFERENCES games(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE create_run_steps (
  id VARCHAR(36) PRIMARY KEY,
  job_id VARCHAR(36) NOT NULL,
  step_no INT NOT NULL,
  stage VARCHAR(50) NOT NULL,
  status VARCHAR(30) NOT NULL,
  message TEXT,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_steps_job_no (job_id, step_no),
  CONSTRAINT fk_steps_job FOREIGN KEY (job_id) REFERENCES create_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE ai_configs (
  user_id VARCHAR(36) PRIMARY KEY,
  base_url VARCHAR(2048) NOT NULL,
  model VARCHAR(255) NOT NULL,
  api_key_ciphertext TEXT NOT NULL,
  provider VARCHAR(80) NOT NULL,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_ai_configs_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE outbox_events (
  id VARCHAR(36) PRIMARY KEY,
  aggregate_id VARCHAR(36) NOT NULL,
  event_type VARCHAR(80) NOT NULL,
  payload JSON,
  status VARCHAR(20) NOT NULL DEFAULT 'pending',
  attempts INT NOT NULL DEFAULT 0,
  available_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  sending_at DATETIME(6),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  sent_at DATETIME(6),
  INDEX ix_outbox_due (status, available_at, created_at),
  UNIQUE KEY uq_outbox_aggregate_type (aggregate_id, event_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE model_usage_events (
  id VARCHAR(36) PRIMARY KEY,
  job_id VARCHAR(36) NOT NULL,
  provider VARCHAR(80) NOT NULL,
  model VARCHAR(255) NOT NULL,
  prompt_tokens BIGINT NOT NULL,
  completion_tokens BIGINT NOT NULL,
  total_tokens BIGINT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_usage_job (job_id),
  CONSTRAINT fk_usage_job FOREIGN KEY (job_id) REFERENCES create_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
