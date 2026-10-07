CREATE TABLE create_chat_sessions (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  create_type VARCHAR(10) NOT NULL,
  project_id VARCHAR(36),
  funding_mode VARCHAR(10) NOT NULL,
  voucher_id VARCHAR(36),
  status VARCHAR(20) NOT NULL DEFAULT 'draft',
  revision INT NOT NULL DEFAULT 0,
  brief_json JSON,
  pending_request_id VARCHAR(36),
  reply_expires_at DATETIME(6),
  job_id VARCHAR(36),
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  INDEX ix_chat_owner (user_id, updated_at),
  CONSTRAINT fk_chat_owner FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_chat_job FOREIGN KEY (job_id) REFERENCES create_jobs(id),
  CONSTRAINT ck_chat_revision CHECK (revision >= 0)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE create_chat_messages (
  id VARCHAR(36) PRIMARY KEY,
  session_id VARCHAR(36) NOT NULL,
  request_id VARCHAR(36) NOT NULL,
  role VARCHAR(16) NOT NULL,
  content TEXT NOT NULL,
  skill_ids_json JSON NOT NULL,
  prompt_tokens BIGINT NOT NULL DEFAULT 0,
  completion_tokens BIGINT NOT NULL DEFAULT 0,
  sequence_no INT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_chat_request_role (session_id, request_id, role),
  UNIQUE KEY uq_chat_sequence (session_id, sequence_no),
  CONSTRAINT fk_chat_message_session FOREIGN KEY (session_id) REFERENCES create_chat_sessions(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
