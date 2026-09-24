from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict


ROOT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env"
API_ENV_FILE = Path(__file__).resolve().parents[1] / ".env"


class Settings(BaseSettings):
    environment: str = "dev" # dev | staging | prod
    database_url: str = "postgresql+psycopg://gameweare:gameweare@localhost:5432/gameweare"
    minio_endpoint: str = "localhost:9000"
    minio_access_key: str = "minioadmin"
    minio_secret_key: str = "minioadmin"
    minio_bucket: str = "gameweare-games"
    minio_public_base_url: str = "http://localhost:9000/gameweare-games"
    redis_url: str = "redis://localhost:6379/0"
    jwt_secret: str = "dev-change-me"
    jwt_ttl_seconds: int = 604800
    web_base_url: str = "http://localhost:1314"
    google_client_id: str = ""
    google_client_secret: str = ""
    google_redirect_uri: str = "http://localhost:8080/auth/google/callback"
    api_port: int = 8080
    ai_config_encryption_secret: str = "dev-change-me-32bytes"
    create_static_generation: bool = False
    create_validate_llm_config: bool = True
    create_recent_game_ttl_seconds: int = 604800
    llm_request_timeout_seconds: float = 600.0
    create_worktree_enabled: bool = True
    create_worktree_base_ref: str = "HEAD"
    create_worktree_cleanup_policy: str = "auto_on_success"
    play_stats_flush_interval_seconds: float = 10.0
    maintainer_email: str = ""
    maintainer_password: str = ""
    maintainer_display_name: str = "Platform Maintainer"
    db_pool_min_size: int = 5
    db_pool_max_size: int = 10
    db_pool_max_idle_lifetime: float = 300.0
    db_pool_max_lifetime: float = 3600.0
    db_pool_timeout: float = 30.0

    model_config = SettingsConfigDict(env_file=(ROOT_ENV_FILE, API_ENV_FILE), extra="ignore")


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    if settings.environment != "dev":
     # JWT_SECRET 校验
        if settings.jwt_secret == "dev-change-me":
            raise ValueError(
                "JWT_SECRET is using default value 'dev-change-me'. "
                "Please set a strong secret via environment variable."
            )
        if len(settings.jwt_secret) < 32:
            raise ValueError(
                f"JWT_SECRET must be at least 32 characters, got {len(settings.jwt_secret)}. "
                "Please set a strong secret via environment variable."
            )

        # AI_CONFIG_ENCRYPTION_SECRET 校验
        if settings.ai_config_encryption_secret == "dev-change-me-32bytes":
            raise ValueError(
                "AI_CONFIG_ENCRYPTION_SECRET is using default value. "
                "Please set a strong 32-byte secret via environment variable."
            )
        if len(settings.ai_config_encryption_secret) < 32:
            raise ValueError(
                f"AI_CONFIG_ENCRYPTION_SECRET must be at least 32 characters, got {len(settings.ai_config_encryption_secret)}. "
                "Please set a strong secret via environment variable."
            )
    return settings