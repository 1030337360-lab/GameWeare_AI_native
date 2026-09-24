CREATE TABLE create_job_workflows (
  job_id VARCHAR(36) PRIMARY KEY,
  phase VARCHAR(40) NOT NULL,
  preview_json JSON,
  selected_candidate_id VARCHAR(80),
  prompt_tokens BIGINT NOT NULL DEFAULT 0,
  completion_tokens BIGINT NOT NULL DEFAULT 0,
  used_tokens BIGINT NOT NULL DEFAULT 0,
  updated_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6) ON UPDATE CURRENT_TIMESTAMP(6),
  CONSTRAINT fk_workflow_job FOREIGN KEY (job_id) REFERENCES create_jobs(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

CREATE TABLE create_job_inputs (
  job_id VARCHAR(36) NOT NULL,
  asset_id VARCHAR(36) NOT NULL,
  PRIMARY KEY (job_id, asset_id),
  CONSTRAINT fk_job_input_job FOREIGN KEY (job_id) REFERENCES create_jobs(id),
  CONSTRAINT fk_job_input_asset FOREIGN KEY (asset_id) REFERENCES assets(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
