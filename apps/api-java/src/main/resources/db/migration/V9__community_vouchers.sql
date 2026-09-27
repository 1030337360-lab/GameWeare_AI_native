CREATE TABLE creator_follows (
  user_id VARCHAR(36) NOT NULL,
  creator_id VARCHAR(36) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id, creator_id),
  INDEX ix_creator_follows_creator (creator_id, user_id),
  CONSTRAINT fk_creator_follows_user FOREIGN KEY (user_id) REFERENCES users(id),
  CONSTRAINT fk_creator_follows_creator FOREIGN KEY (creator_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE daily_checkins (
  user_id VARCHAR(36) NOT NULL,
  checkin_day DATE NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id, checkin_day),
  INDEX ix_daily_checkins_day (checkin_day),
  CONSTRAINT fk_daily_checkins_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE checkin_streaks (
  user_id VARCHAR(36) PRIMARY KEY,
  streak_start DATE,
  last_day DATE,
  current_streak INT NOT NULL DEFAULT 0,
  longest_streak INT NOT NULL DEFAULT 0,
  total_days INT NOT NULL DEFAULT 0,
  CONSTRAINT fk_checkin_streaks_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE checkin_reward_rules (
  milestone INT PRIMARY KEY,
  voucher_count INT NOT NULL,
  validity_days INT NOT NULL DEFAULT 30,
  enabled BOOLEAN NOT NULL DEFAULT TRUE,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT ck_reward_milestone CHECK (milestone > 0),
  CONSTRAINT ck_reward_count CHECK (voucher_count BETWEEN 1 AND 10)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
INSERT INTO checkin_reward_rules(milestone,voucher_count,validity_days) VALUES (7,1,30),(30,1,30);

CREATE TABLE checkin_awards (
  user_id VARCHAR(36) NOT NULL,
  streak_start DATE NOT NULL,
  milestone INT NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (user_id, streak_start, milestone),
  CONSTRAINT fk_checkin_awards_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE voucher_campaigns (
  id VARCHAR(36) PRIMARY KEY,
  title VARCHAR(160) NOT NULL,
  starts_at DATETIME(6) NOT NULL,
  ends_at DATETIME(6) NOT NULL,
  total_stock INT NOT NULL,
  remaining_stock INT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'scheduled',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  CONSTRAINT ck_campaign_stock CHECK (total_stock > 0 AND remaining_stock >= 0 AND remaining_stock <= total_stock),
  CONSTRAINT ck_campaign_dates CHECK (ends_at > starts_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE voucher_claims (
  id VARCHAR(36) PRIMARY KEY,
  campaign_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(36) NOT NULL,
  remaining_after INT NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'issued',
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  UNIQUE KEY uq_claim_campaign_user (campaign_id,user_id),
  INDEX ix_claim_campaign_status (campaign_id,status),
  CONSTRAINT fk_claim_campaign FOREIGN KEY (campaign_id) REFERENCES voucher_campaigns(id),
  CONSTRAINT fk_claim_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE generation_vouchers (
  id VARCHAR(36) PRIMARY KEY,
  user_id VARCHAR(36) NOT NULL,
  source_type VARCHAR(20) NOT NULL,
  source_id VARCHAR(120) NOT NULL,
  status VARCHAR(20) NOT NULL DEFAULT 'available',
  reserved_job_id VARCHAR(36),
  expires_at DATETIME(6) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  used_at DATETIME(6),
  UNIQUE KEY uq_voucher_source (user_id,source_type,source_id),
  UNIQUE KEY uq_voucher_job (reserved_job_id),
  INDEX ix_vouchers_user_status (user_id,status,expires_at),
  CONSTRAINT fk_voucher_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

ALTER TABLE create_jobs
  ADD COLUMN funding_mode VARCHAR(16) NOT NULL DEFAULT 'byok',
  ADD COLUMN voucher_id VARCHAR(36),
  ADD INDEX ix_jobs_voucher (voucher_id);
