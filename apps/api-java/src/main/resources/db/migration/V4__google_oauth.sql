ALTER TABLE users MODIFY password_hash VARCHAR(255) NULL;

CREATE TABLE oauth_accounts (
  provider VARCHAR(30) NOT NULL,
  provider_subject VARCHAR(255) NOT NULL,
  user_id VARCHAR(36) NOT NULL,
  provider_email VARCHAR(254) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (provider, provider_subject),
  UNIQUE KEY uq_oauth_provider_user (provider, user_id),
  CONSTRAINT fk_oauth_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
