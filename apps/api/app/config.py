from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+psycopg://yahaha:yahaha@localhost:5432/yahaha"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "yahaha-games"
    minio_public_base_url: str = "http://localhost:9000/yahaha-games"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-change-me"
    jwt_ttl_seconds: int = 604800
    web_base_url: str = "http://localhost:1314"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/auth/google/callback"
    api_port: int = 8080
    ai_config_encryption_secret: str = "dev-change-me-32bytes"
    create_static_generation: bool = True
    create_validate_llm_config: bool = True
    create_recent_game_ttl_seconds: int = 604800
    llm_request_timeout_seconds: float = 12.0
    create_worktree_enabled: bool = False
    create_worktree_base_ref: str = "HEAD"
    create_worktree_cleanup_policy: str = "manual"

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


@lru_cache
def get_settings() -> Settings:
    return Settings()
