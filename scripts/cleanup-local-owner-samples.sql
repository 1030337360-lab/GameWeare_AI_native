-- One-time cleanup for assistant-created samples on the real account.
-- The owner explicitly requested removal; retain the pre-cleanup SQL and MinIO backups.
START TRANSACTION;
CREATE TEMPORARY TABLE owner_sample_games (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT id FROM games WHERE author_id='0cefcfdc-e3f6-478f-8cb2-f15540cc607c'
    AND id IN ('e164e6db-0db1-4915-9ae8-07b18d2f95ca','a01c9fa2-df8a-44f5-82e2-5292872ab4b5',
               '26f172b3-4842-4942-8c9b-81fbb75cd57e','3c17204d-1f9a-413b-b27c-ce10ec62d371');
CREATE TEMPORARY TABLE owner_sample_jobs (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT id FROM create_jobs WHERE user_id='0cefcfdc-e3f6-478f-8cb2-f15540cc607c'
    AND deleted_at IS NOT NULL AND id IN
      ('f431bfdb-fced-450c-af21-0fe3db8b7d13','4235e62d-3a5a-4d19-ba2b-8c08e297aa46',
       'd8c0b45c-3046-4143-b53f-24f315640b5c','3405e451-53e9-484c-b526-af10351ac6a5',
       '96558c7a-c0e7-4452-a330-ccdcbee9e195','76ebfe52-b345-460d-9a21-b98d2ecc504f',
       '9e884b70-6b86-47d5-9578-7dca14446953','beab687f-3d91-4c69-a898-eeff64e52f28',
       '849bb8d3-9e40-4d3f-af44-c65f4eb4b175','4e382393-b87f-473f-bcb5-1db76b089735',
       '6192663e-1aac-4939-a561-0781c6d3aa8b','6ee67106-a502-41d7-91f1-d91aed4ed3a4');
CREATE TEMPORARY TABLE owner_sample_projects (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT p.id FROM create_projects p WHERE p.user_id='0cefcfdc-e3f6-478f-8cb2-f15540cc607c'
    AND p.status='archived'
    AND NOT EXISTS (SELECT 1 FROM create_jobs j WHERE j.project_id=p.id AND j.id NOT IN (SELECT id FROM owner_sample_jobs));
CREATE TEMPORARY TABLE owner_sample_assets (id VARCHAR(36) PRIMARY KEY) ENGINE=MEMORY AS
  SELECT a.id FROM assets a LEFT JOIN owner_sample_games g ON g.id=a.game_id
    LEFT JOIN owner_sample_jobs j ON j.id=a.job_id
    WHERE g.id IS NOT NULL OR j.id IS NOT NULL;

DELETE i FROM create_job_inputs i LEFT JOIN owner_sample_jobs j ON j.id=i.job_id
  LEFT JOIN owner_sample_assets a ON a.id=i.asset_id WHERE j.id IS NOT NULL OR a.id IS NOT NULL;
DELETE m FROM agent_project_memory m LEFT JOIN owner_sample_projects p ON p.id=m.project_id
  LEFT JOIN owner_sample_jobs j ON j.id=m.source_job_id
  WHERE p.id IS NOT NULL OR j.id IS NOT NULL;
DELETE c FROM agent_model_calls c JOIN owner_sample_jobs j ON j.id=c.job_id;
DELETE w FROM create_job_workflows w JOIN owner_sample_jobs j ON j.id=w.job_id;
DELETE s FROM create_run_steps s JOIN owner_sample_jobs j ON j.id=s.job_id;
DELETE e FROM model_usage_events e JOIN owner_sample_jobs j ON j.id=e.job_id;
DELETE e FROM outbox_events e JOIN owner_sample_jobs j ON j.id=e.aggregate_id;
DELETE l FROM game_likes l JOIN owner_sample_games g ON g.id=l.game_id;
DELETE f FROM game_favorites f JOIN owner_sample_games g ON g.id=f.game_id;
DELETE p FROM play_events p JOIN owner_sample_games g ON g.id=p.game_id;
DELETE p FROM play_count_dedupe p JOIN owner_sample_games g ON g.id=p.game_id;
DELETE t FROM game_tags t JOIN owner_sample_games g ON g.id=t.game_id;
DELETE r FROM moderation_reviews r JOIN owner_sample_games g ON g.id=r.target_id WHERE r.target_type='game';
DELETE a FROM assets a JOIN owner_sample_assets x ON x.id=a.id;
DELETE j FROM create_jobs j JOIN owner_sample_jobs x ON x.id=j.id;
DELETE p FROM create_projects p JOIN owner_sample_projects x ON x.id=p.id;
DELETE v FROM game_versions v JOIN owner_sample_games g ON g.id=v.game_id;
DELETE g FROM games g JOIN owner_sample_games x ON x.id=g.id;

SELECT (SELECT COUNT(*) FROM owner_sample_jobs) AS removed_sample_jobs,
       (SELECT COUNT(*) FROM owner_sample_games) AS removed_sample_games,
       (SELECT COUNT(*) FROM owner_sample_projects) AS removed_sample_projects;
COMMIT;
