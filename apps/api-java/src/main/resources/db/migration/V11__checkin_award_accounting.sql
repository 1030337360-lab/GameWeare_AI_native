ALTER TABLE checkin_awards
  ADD COLUMN award_day DATE NULL,
  ADD COLUMN awarded_count INT NOT NULL DEFAULT 1,
  ADD INDEX ix_checkin_awards_month (user_id, award_day);
