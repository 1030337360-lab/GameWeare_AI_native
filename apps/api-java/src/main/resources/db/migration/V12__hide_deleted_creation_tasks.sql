ALTER TABLE create_jobs ADD COLUMN deleted_at DATETIME(6) NULL;
CREATE INDEX idx_create_jobs_owner_visible ON create_jobs(user_id, deleted_at, created_at);
