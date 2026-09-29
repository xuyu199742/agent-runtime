from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import make_url


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql+asyncpg://agent:agent@localhost:5434/agent"
    redis_url: str = "redis://localhost:6380/0"
    model_secret_key: str | None = Field(default=None, repr=False, exclude=True)
    dev_user_id: str = "local-dev-user"
    http_tool_allowed_hosts: str = ""
    context_max_messages: int = Field(default=30, ge=1, le=100)
    log_level: str = "INFO"

    @property
    def checkpoint_database_url(self) -> str:
        # SQLAlchemy 和 LangGraph 使用不同驱动，但连接同一数据库。
        return (
            make_url(self.database_url)
            .set(drivername="postgresql")
            .render_as_string(hide_password=False)
        )


@lru_cache
def get_settings() -> Settings:
    return Settings()
