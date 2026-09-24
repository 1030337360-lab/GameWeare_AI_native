INSERT INTO users (id, email, display_name, avatar_url, role, status)
VALUES
  ('00000000-0000-0000-0000-000000000001', 'system@gameweare.local', 'Gameweare System', NULL, 'admin', 'active'),
  ('00000000-0000-0000-0000-000000000002', 'demo@gameweare.local', 'xiaoling', NULL, 'user', 'active'),
  ('00000000-0000-0000-0000-000000000003', 'creator@gameweare.local', 'emanfatima', NULL, 'user', 'active'),
  ('00000000-0000-0000-0000-000000000004', 'builder@gameweare.local', 'Majisok', NULL, 'user', 'active')
ON CONFLICT (id) DO UPDATE SET
  email = EXCLUDED.email,
  display_name = EXCLUDED.display_name,
  role = EXCLUDED.role,
  status = EXCLUDED.status;

INSERT INTO games (
  id,
  slug,
  author_id,
  title,
  description,
  visibility,
  publish_status,
  plays_count,
  metadata,
  published_at
)
VALUES
  (
    '10000000-0000-0000-0000-000000000001',
    'astro-ludo',
    '00000000-0000-0000-0000-000000000002',
    'Astro Ludo',
    'Fast tabletop moves in a glowing space arcade.',
    'public',
    'published',
    1200000,
    '{"section": "Players'' Choice"}'::jsonb,
    '2026-06-18T10:00:00Z'
  ),
  (
    '10000000-0000-0000-0000-000000000002',
    'color-bloom',
    '00000000-0000-0000-0000-000000000003',
    'Color Bloom',
    'A bright matching puzzle generated from a single prompt.',
    'public',
    'published',
    700000,
    '{"section": "Trending"}'::jsonb,
    '2026-06-18T11:00:00Z'
  ),
  (
    '10000000-0000-0000-0000-000000000003',
    'rail-in-air',
    '00000000-0000-0000-0000-000000000004',
    'Rail in Air',
    'Balance a flying rail cart through neon gates.',
    'public',
    'published',
    4500000,
    '{"section": "Recommended For You"}'::jsonb,
    '2026-06-18T12:00:00Z'
  )
ON CONFLICT (id) DO UPDATE SET
  slug = EXCLUDED.slug,
  author_id = EXCLUDED.author_id,
  title = EXCLUDED.title,
  description = EXCLUDED.description,
  visibility = EXCLUDED.visibility,
  publish_status = EXCLUDED.publish_status,
  plays_count = EXCLUDED.plays_count,
  metadata = EXCLUDED.metadata,
  published_at = EXCLUDED.published_at;

INSERT INTO generation_jobs (
  id,
  creator_id,
  game_id,
  prompt,
  input_payload,
  status,
  current_stage,
  started_at,
  completed_at,
  created_at
)
VALUES (
  '20000000-0000-0000-0000-000000000001',
  '00000000-0000-0000-0000-000000000003',
  '10000000-0000-0000-0000-000000000002',
  'Create a bright matching puzzle generated from a single prompt.',
  '{"source": "seed", "modality": ["text"]}'::jsonb,
  'completed',
  'publisher',
  '2026-06-18T10:45:00Z',
  '2026-06-18T10:58:00Z',
  '2026-06-18T10:45:00Z'
)
ON CONFLICT (id) DO UPDATE SET
  creator_id = EXCLUDED.creator_id,
  game_id = EXCLUDED.game_id,
  prompt = EXCLUDED.prompt,
  input_payload = EXCLUDED.input_payload,
  status = EXCLUDED.status,
  current_stage = EXCLUDED.current_stage,
  started_at = EXCLUDED.started_at,
  completed_at = EXCLUDED.completed_at;

INSERT INTO game_versions (
  id,
  game_id,
  version_no,
  source_job_id,
  runtime,
  entry_file,
  build_status,
  safety_status,
  storage_prefix,
  metadata,
  created_at
)
VALUES
  (
    '30000000-0000-0000-0000-000000000001',
    '10000000-0000-0000-0000-000000000001',
    1,
    NULL,
    'iframe-html5',
    'index.html',
    'succeeded',
    'passed',
    'games/astro-ludo/versions/1',
    '{"seed": true}'::jsonb,
    '2026-06-18T10:00:00Z'
  ),
  (
    '30000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000002',
    1,
    '20000000-0000-0000-0000-000000000001',
    'iframe-html5',
    'index.html',
    'succeeded',
    'passed',
    'games/color-bloom/versions/1',
    '{"seed": true, "createdByAgent": true}'::jsonb,
    '2026-06-18T11:00:00Z'
  ),
  (
    '30000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000003',
    1,
    NULL,
    'iframe-html5',
    'index.html',
    'succeeded',
    'passed',
    'games/rail-in-air/versions/1',
    '{"seed": true}'::jsonb,
    '2026-06-18T12:00:00Z'
  )
ON CONFLICT (game_id, version_no) DO UPDATE SET
  source_job_id = EXCLUDED.source_job_id,
  runtime = EXCLUDED.runtime,
  entry_file = EXCLUDED.entry_file,
  build_status = EXCLUDED.build_status,
  safety_status = EXCLUDED.safety_status,
  storage_prefix = EXCLUDED.storage_prefix,
  metadata = EXCLUDED.metadata;

INSERT INTO assets (
  id,
  owner_id,
  game_id,
  version_id,
  job_id,
  kind,
  bucket,
  object_key,
  public_url,
  content_type,
  size_bytes
)
VALUES
  (
    '40000000-0000-0000-0000-000000000001',
    '00000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    NULL,
    NULL,
    'cover',
    'external',
    'covers/astro-ludo.jpg',
    'https://images.unsplash.com/photo-1614728894747-a83421e2b9c9?auto=format&fit=crop&w=900&q=80',
    'image/jpeg',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000002',
    '00000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000002',
    NULL,
    '20000000-0000-0000-0000-000000000001',
    'cover',
    'external',
    'covers/color-bloom.jpg',
    'https://images.unsplash.com/photo-1550684848-fac1c5b4e853?auto=format&fit=crop&w=900&q=80',
    'image/jpeg',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000003',
    '00000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000003',
    NULL,
    NULL,
    'cover',
    'external',
    'covers/rail-in-air.jpg',
    'https://images.unsplash.com/photo-1519608487953-e999c86e7455?auto=format&fit=crop&w=900&q=80',
    'image/jpeg',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000011',
    '00000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    NULL,
    'manifest',
    'gameweare-games',
    'games/astro-ludo/versions/1/manifest.json',
    'http://localhost:9000/gameweare-games/games/astro-ludo/versions/1/manifest.json',
    'application/json',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000012',
    '00000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000001',
    'manifest',
    'gameweare-games',
    'games/color-bloom/versions/1/manifest.json',
    'http://localhost:9000/gameweare-games/games/color-bloom/versions/1/manifest.json',
    'application/json',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000013',
    '00000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000003',
    NULL,
    'manifest',
    'gameweare-games',
    'games/rail-in-air/versions/1/manifest.json',
    'http://localhost:9000/gameweare-games/games/rail-in-air/versions/1/manifest.json',
    'application/json',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000021',
    '00000000-0000-0000-0000-000000000002',
    '10000000-0000-0000-0000-000000000001',
    '30000000-0000-0000-0000-000000000001',
    NULL,
    'bundle',
    'gameweare-games',
    'games/astro-ludo/versions/1/index.html',
    'http://localhost:8080/bundles/games/astro-ludo/index.html',
    'text/html',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000022',
    '00000000-0000-0000-0000-000000000003',
    '10000000-0000-0000-0000-000000000002',
    '30000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000001',
    'bundle',
    'gameweare-games',
    'games/color-bloom/versions/1/index.html',
    'http://localhost:8080/bundles/games/color-bloom/index.html',
    'text/html',
    0
  ),
  (
    '40000000-0000-0000-0000-000000000023',
    '00000000-0000-0000-0000-000000000004',
    '10000000-0000-0000-0000-000000000003',
    '30000000-0000-0000-0000-000000000003',
    NULL,
    'bundle',
    'gameweare-games',
    'games/rail-in-air/versions/1/index.html',
    'http://localhost:8080/bundles/games/rail-in-air/index.html',
    'text/html',
    0
  )
ON CONFLICT (id) DO UPDATE SET
  owner_id = EXCLUDED.owner_id,
  game_id = EXCLUDED.game_id,
  version_id = EXCLUDED.version_id,
  job_id = EXCLUDED.job_id,
  kind = EXCLUDED.kind,
  bucket = EXCLUDED.bucket,
  object_key = EXCLUDED.object_key,
  public_url = EXCLUDED.public_url,
  content_type = EXCLUDED.content_type,
  size_bytes = EXCLUDED.size_bytes;

UPDATE game_versions
SET manifest_asset_id = CASE id
  WHEN '30000000-0000-0000-0000-000000000001' THEN '40000000-0000-0000-0000-000000000011'::uuid
  WHEN '30000000-0000-0000-0000-000000000002' THEN '40000000-0000-0000-0000-000000000012'::uuid
  WHEN '30000000-0000-0000-0000-000000000003' THEN '40000000-0000-0000-0000-000000000013'::uuid
  ELSE manifest_asset_id
END
WHERE id IN (
  '30000000-0000-0000-0000-000000000001',
  '30000000-0000-0000-0000-000000000002',
  '30000000-0000-0000-0000-000000000003'
);

UPDATE games
SET
  cover_asset_id = CASE id
    WHEN '10000000-0000-0000-0000-000000000001' THEN '40000000-0000-0000-0000-000000000001'::uuid
    WHEN '10000000-0000-0000-0000-000000000002' THEN '40000000-0000-0000-0000-000000000002'::uuid
    WHEN '10000000-0000-0000-0000-000000000003' THEN '40000000-0000-0000-0000-000000000003'::uuid
    ELSE cover_asset_id
  END,
  current_version_id = CASE id
    WHEN '10000000-0000-0000-0000-000000000001' THEN '30000000-0000-0000-0000-000000000001'::uuid
    WHEN '10000000-0000-0000-0000-000000000002' THEN '30000000-0000-0000-0000-000000000002'::uuid
    WHEN '10000000-0000-0000-0000-000000000003' THEN '30000000-0000-0000-0000-000000000003'::uuid
    ELSE current_version_id
  END
WHERE id IN (
  '10000000-0000-0000-0000-000000000001',
  '10000000-0000-0000-0000-000000000002',
  '10000000-0000-0000-0000-000000000003'
);

UPDATE generation_jobs
SET version_id = '30000000-0000-0000-0000-000000000002'
WHERE id = '20000000-0000-0000-0000-000000000001';

INSERT INTO tags (name)
VALUES
  ('Board'),
  ('Arcade'),
  ('Puzzle'),
  ('Generated'),
  ('Runner'),
  ('Physics')
ON CONFLICT (name) DO NOTHING;

INSERT INTO game_tags (game_id, tag_id)
SELECT g.id, t.id
FROM (
  VALUES
    ('astro-ludo', 'Board'),
    ('astro-ludo', 'Arcade'),
    ('color-bloom', 'Puzzle'),
    ('color-bloom', 'Generated'),
    ('rail-in-air', 'Runner'),
    ('rail-in-air', 'Physics')
) AS seed(slug, tag_name)
JOIN games g ON g.slug = seed.slug
JOIN tags t ON t.name = seed.tag_name
ON CONFLICT DO NOTHING;

INSERT INTO agent_runs (
  id,
  job_id,
  stage,
  status,
  input_summary,
  output_summary,
  log,
  started_at,
  completed_at,
  created_at
)
VALUES
  (
    '50000000-0000-0000-0000-000000000001',
    '20000000-0000-0000-0000-000000000001',
    'planner',
    'succeeded',
    'Seed prompt for Color Bloom.',
    'Planned a bright matching puzzle with color tiles.',
    '{"seed": true}'::jsonb,
    '2026-06-18T10:45:00Z',
    '2026-06-18T10:48:00Z',
    '2026-06-18T10:45:00Z'
  ),
  (
    '50000000-0000-0000-0000-000000000002',
    '20000000-0000-0000-0000-000000000001',
    'game_code',
    'succeeded',
    'Generated HTML5 puzzle bundle.',
    'Bundle validated for iframe runtime.',
    '{"seed": true}'::jsonb,
    '2026-06-18T10:48:00Z',
    '2026-06-18T10:54:00Z',
    '2026-06-18T10:48:00Z'
  ),
  (
    '50000000-0000-0000-0000-000000000003',
    '20000000-0000-0000-0000-000000000001',
    'publisher',
    'succeeded',
    'Uploaded bundle and manifest metadata.',
    'Published Color Bloom to Home.',
    '{"seed": true}'::jsonb,
    '2026-06-18T10:54:00Z',
    '2026-06-18T10:58:00Z',
    '2026-06-18T10:54:00Z'
  )
ON CONFLICT (id) DO UPDATE SET
  status = EXCLUDED.status,
  input_summary = EXCLUDED.input_summary,
  output_summary = EXCLUDED.output_summary,
  log = EXCLUDED.log,
  started_at = EXCLUDED.started_at,
  completed_at = EXCLUDED.completed_at;

INSERT INTO job_artifacts (job_id, asset_id, purpose)
VALUES
  ('20000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000012', 'manifest'),
  ('20000000-0000-0000-0000-000000000001', '40000000-0000-0000-0000-000000000022', 'final')
ON CONFLICT DO NOTHING;
