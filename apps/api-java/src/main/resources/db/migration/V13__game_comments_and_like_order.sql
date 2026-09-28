ALTER TABLE games ADD COLUMN comments_count BIGINT NOT NULL DEFAULT 0;
CREATE INDEX ix_games_like_order ON games (publish_status, visibility, likes_count DESC, published_at DESC, id DESC);

CREATE TABLE game_comments (
  id VARCHAR(36) PRIMARY KEY,
  game_id VARCHAR(36) NOT NULL,
  user_id VARCHAR(36) NOT NULL,
  content VARCHAR(1000) NOT NULL,
  created_at DATETIME(6) NOT NULL DEFAULT CURRENT_TIMESTAMP(6),
  deleted_at DATETIME(6),
  INDEX ix_comments_game_page (game_id, deleted_at, created_at DESC, id DESC),
  INDEX ix_comments_user (user_id, created_at),
  CONSTRAINT fk_comments_game FOREIGN KEY (game_id) REFERENCES games(id),
  CONSTRAINT fk_comments_user FOREIGN KEY (user_id) REFERENCES users(id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
