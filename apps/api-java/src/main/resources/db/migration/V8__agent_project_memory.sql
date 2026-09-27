CREATE TABLE agent_project_memory (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  project_id VARCHAR(36) NOT NULL,
  source_job_id VARCHAR(36) NOT NULL,
  game_version_id VARCHAR(36) NOT NULL,
  summary TEXT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_agent_memory_job (source_job_id),
  INDEX ix_agent_memory_scope (user_id, project_id, created_at),
  CONSTRAINT fk_agent_memory_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_agent_memory_project FOREIGN KEY (project_id) REFERENCES create_projects(id),
  CONSTRAINT fk_agent_memory_job FOREIGN KEY (source_job_id) REFERENCES create_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
