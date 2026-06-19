CREATE TABLE IF NOT EXISTS user_ai_configs (
  id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
  user_id uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  base_url text NOT NULL,
  model varchar(120) NOT NULL,
  api_key_encrypted text NOT NULL,
  provider varchar(40) NOT NULL DEFAULT 'openai-compatible',
  created_at timestamptz NOT NULL DEFAULT now(),
  updated_at timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id)
);

DROP TRIGGER IF EXISTS set_user_ai_configs_updated_at ON user_ai_configs;
CREATE TRIGGER set_user_ai_configs_updated_at
  BEFORE UPDATE ON user_ai_configs
  FOR EACH ROW EXECUTE FUNCTION set_updated_at();
