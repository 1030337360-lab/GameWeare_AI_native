CREATE TABLE checkin_reward_rule_changes (
  milestone INT NOT NULL,
  effective_at DATETIME(6) NOT NULL,
  voucher_count INT NOT NULL,
  validity_days INT NOT NULL,
  enabled BOOLEAN NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  PRIMARY KEY (milestone, effective_at),
  CONSTRAINT ck_future_reward_milestone CHECK (milestone BETWEEN 1 AND 365),
  CONSTRAINT ck_future_reward_count CHECK (voucher_count BETWEEN 1 AND 2)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
