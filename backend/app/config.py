import logging
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    # Supabase
    supabase_url: str = ""
    supabase_key: str = ""
    database_url: str = "sqlite+aiosqlite:///./dev.db"

    # S3 / AWS
    s3_bucket: str = ""
    aws_access_key_id: str = ""
    aws_secret_access_key: str = ""
    aws_region: str = "us-east-1"

    # Redis / RQ
    redis_url: str = "redis://localhost:6379"

    # Anthropic
    anthropic_api_key: str = ""

    # CORS
    allowed_origins: str = "http://localhost:5173"

    # Video limits
    max_video_duration_seconds: int = 30
    max_video_size_mb: int = 100

    @property
    def allowed_origins_list(self) -> list[str]:
        return [o.strip() for o in self.allowed_origins.split(",")]


@lru_cache
def get_settings() -> Settings:
    settings = Settings()
    logger.info("Settings loaded (database_url scheme: %s)", settings.database_url.split(":")[0])
    return settings
