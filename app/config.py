from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5434/agent"
    checkpoint_database_url: str = "postgresql://agent:agent@localhost:5434/agent"
    redis_url: str = "redis://localhost:6380/0"
    dev_user_id: str = "local-dev-user"
    http_tool_allowed_hosts: str = ""
    log_level: str = "INFO"


@lru_cache
def get_settings() -> Settings:
    return Settings()
