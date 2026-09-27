CREATE TABLE agent_model_calls (
  id VARCHAR(36) PRIMARY KEY,
  job_id VARCHAR(36) NOT NULL,
  model VARCHAR(255) NOT NULL,
  state VARCHAR(16) NOT NULL,
  provider_reply_id VARCHAR(255),
  prompt_tokens BIGINT,
  completion_tokens BIGINT,
  started_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  ended_at DATETIME(6),
  INDEX ix_agent_model_calls_job (job_id, started_at),
  CONSTRAINT fk_agent_model_calls_job FOREIGN KEY (job_id) REFERENCES create_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
