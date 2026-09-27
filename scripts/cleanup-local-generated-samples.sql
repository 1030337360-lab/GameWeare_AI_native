-- One-time local cleanup, reviewed against the 2026-09-27 database snapshot.
-- Back up gameweare before running. Never use this script against production.
START TRANSACTION;

CREATE TEMPORARY TABLE cleanup_users (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT id FROM users WHERE email LIKE 'ci-%@example.test'
    OR email LIKE 'flow-%@example.test'
    OR email LIKE 'e2e-agentscope-%@example.com';
CREATE TEMPORARY TABLE cleanup_games (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT g.id FROM games g JOIN cleanup_users u ON u.id=g.author_id;
CREATE TEMPORARY TABLE cleanup_projects (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT p.id FROM create_projects p JOIN cleanup_users u ON u.id=p.user_id;
CREATE TEMPORARY TABLE cleanup_jobs (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT j.id FROM create_jobs j JOIN cleanup_users u ON u.id=j.user_id;
CREATE TEMPORARY TABLE cleanup_campaigns (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT id FROM voucher_campaigns WHERE title LIKE 'CI %' OR title='并发验收短时活动';
CREATE TEMPORARY TABLE cleanup_assets (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT a.id FROM assets a LEFT JOIN cleanup_users u ON u.id=a.owner_id
    LEFT JOIN cleanup_games g ON g.id=a.game_id
    LEFT JOIN cleanup_jobs j ON j.id=a.job_id
  WHERE u.id IS NOT NULL OR g.id IS NOT NULL OR j.id IS NOT NULL;

DELETE i FROM create_job_inputs i LEFT JOIN cleanup_jobs j ON j.id=i.job_id
  LEFT JOIN cleanup_assets a ON a.id=i.asset_id WHERE j.id IS NOT NULL OR a.id IS NOT NULL;
DELETE m FROM agent_project_memory m LEFT JOIN cleanup_users u ON u.id=m.user_id
  LEFT JOIN cleanup_projects p ON p.id=m.project_id
  LEFT JOIN cleanup_jobs j ON j.id=m.source_job_id
  WHERE u.id IS NOT NULL OR p.id IS NOT NULL OR j.id IS NOT NULL;
DELETE c FROM agent_model_calls c JOIN cleanup_jobs j ON j.id=c.job_id;
DELETE w FROM create_job_workflows w JOIN cleanup_jobs j ON j.id=w.job_id;
DELETE s FROM create_run_steps s JOIN cleanup_jobs j ON j.id=s.job_id;
DELETE e FROM model_usage_events e JOIN cleanup_jobs j ON j.id=e.job_id;
DELETE e FROM outbox_events e LEFT JOIN cleanup_jobs j ON j.id=e.aggregate_id
  LEFT JOIN cleanup_campaigns c ON c.id=e.aggregate_id WHERE j.id IS NOT NULL OR c.id IS NOT NULL;

DELETE v FROM generation_vouchers v LEFT JOIN cleanup_users u ON u.id=v.user_id
  LEFT JOIN cleanup_campaigns c ON c.id=v.source_id
  WHERE u.id IS NOT NULL OR c.id IS NOT NULL;
DELETE c FROM voucher_claims c LEFT JOIN cleanup_users u ON u.id=c.user_id
  LEFT JOIN cleanup_campaigns a ON a.id=c.campaign_id
  WHERE u.id IS NOT NULL OR a.id IS NOT NULL;
DELETE a FROM checkin_awards a JOIN cleanup_users u ON u.id=a.user_id;
DELETE a FROM checkin_streaks a JOIN cleanup_users u ON u.id=a.user_id;
DELETE a FROM daily_checkins a JOIN cleanup_users u ON u.id=a.user_id;

DELETE l FROM game_likes l LEFT JOIN cleanup_users u ON u.id=l.user_id
  LEFT JOIN cleanup_games g ON g.id=l.game_id WHERE u.id IS NOT NULL OR g.id IS NOT NULL;
DELETE f FROM game_favorites f LEFT JOIN cleanup_users u ON u.id=f.user_id
  LEFT JOIN cleanup_games g ON g.id=f.game_id WHERE u.id IS NOT NULL OR g.id IS NOT NULL;
DELETE p FROM play_events p LEFT JOIN cleanup_users u ON u.id=p.user_id
  LEFT JOIN cleanup_games g ON g.id=p.game_id WHERE u.id IS NOT NULL OR g.id IS NOT NULL;
DELETE p FROM play_count_dedupe p JOIN cleanup_games g ON g.id=p.game_id;
DELETE t FROM game_tags t JOIN cleanup_games g ON g.id=t.game_id;
DELETE f FROM creator_follows f LEFT JOIN cleanup_users u ON u.id=f.user_id
  LEFT JOIN users c ON c.id=f.creator_id
  WHERE u.id IS NOT NULL OR c.email LIKE 'ci-%@example.test'
    OR c.email LIKE 'flow-%@example.test' OR c.email LIKE 'e2e-agentscope-%@example.com';
DELETE r FROM moderation_reviews r LEFT JOIN cleanup_users u ON u.id=r.reviewer_id
  LEFT JOIN cleanup_games g ON g.id=r.target_id WHERE u.id IS NOT NULL OR g.id IS NOT NULL;
DELETE a FROM audit_logs a JOIN cleanup_users u ON u.id=a.actor_user_id;

DELETE a FROM assets a JOIN cleanup_assets x ON x.id=a.id;
DELETE j FROM create_jobs j JOIN cleanup_jobs x ON x.id=j.id;
DELETE p FROM create_projects p JOIN cleanup_projects x ON x.id=p.id;
DELETE v FROM game_versions v JOIN cleanup_games g ON g.id=v.game_id;
DELETE g FROM games g JOIN cleanup_games x ON x.id=g.id;
DELETE c FROM voucher_campaigns c JOIN cleanup_campaigns x ON x.id=c.id;

DELETE a FROM ai_configs a JOIN cleanup_users u ON u.id=a.user_id;
DELETE o FROM oauth_accounts o JOIN cleanup_users u ON u.id=o.user_id;
DELETE s FROM user_sessions s JOIN cleanup_users u ON u.id=s.user_id;
DELETE l FROM token_ledger l JOIN cleanup_users u ON u.id=l.user_id;
DELETE a FROM token_accounts a JOIN cleanup_users u ON u.id=a.user_id;
DELETE u FROM users u JOIN cleanup_users x ON x.id=u.id;

-- Hide only assistant-created samples on the real account. Keep the click game
-- that the owner subsequently optimized with a Chinese prompt.
UPDATE games SET publish_status='archived',visibility='private',updated_at=NOW(6)
  WHERE id IN ('e164e6db-0db1-4915-9ae8-07b18d2f95ca',
               'a01c9fa2-df8a-44f5-82e2-5292872ab4b5',
               '26f172b3-4842-4942-8c9b-81fbb75cd57e',
               '3c17204d-1f9a-413b-b27c-ce10ec62d371')
    AND author_id='0cefcfdc-e3f6-478f-8cb2-f15540cc607c';
UPDATE create_jobs SET deleted_at=NOW(6),updated_at=NOW(6)
  WHERE user_id='0cefcfdc-e3f6-478f-8cb2-f15540cc607c'
    AND id IN ('f431bfdb-fced-450c-af21-0fe3db8b7d13','4235e62d-3a5a-4d19-ba2b-8c08e297aa46',
               'd8c0b45c-3046-4143-b53f-24f315640b5c','3405e451-53e9-484c-b526-af10351ac6a5',
               '96558c7a-c0e7-4452-a330-ccdcbee9e195','76ebfe52-b345-460d-9a21-b98d2ecc504f',
               '9e884b70-6b86-47d5-9578-7dca14446953','beab687f-3d91-4c69-a898-eeff64e52f28',
               '849bb8d3-9e40-4d3f-af44-c65f4eb4b175','4e382393-b87f-473f-bcb5-1db76b089735',
               '6192663e-1aac-4939-a561-0781c6d3aa8b','6ee67106-a502-41d7-91f1-d91aed4ed3a4');
UPDATE create_projects p SET p.status='archived',p.updated_at=NOW(6)
  WHERE p.user_id='0cefcfdc-e3f6-478f-8cb2-f15540cc607c'
    AND NOT EXISTS (SELECT 1 FROM create_jobs j WHERE j.project_id=p.id AND j.deleted_at IS NULL);

SELECT (SELECT COUNT(*) FROM cleanup_users) AS removed_test_users,
       (SELECT COUNT(*) FROM cleanup_games) AS removed_test_games,
       (SELECT COUNT(*) FROM cleanup_campaigns) AS removed_test_campaigns;
COMMIT;
