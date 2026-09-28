import os

from langchain_openai import ChatOpenAI

from app.infrastructure.database import ModelConfig


def build_model(config: ModelConfig) -> ChatOpenAI:
    if not config.enabled or config.provider not in {"openai", "openai-compatible"}:
        raise ValueError("模型配置不可用")
    if config.provider == "openai-compatible" and not config.base_url:
        raise ValueError("OpenAI-compatible 模型必须配置 base_url")
    api_key = os.getenv(config.api_key_env)
    if not api_key and config.provider == "openai":
        raise ValueError(f"缺少模型凭证环境变量: {config.api_key_env}")
    options = config.config or {}
    return ChatOpenAI(
        model=config.model_name,
        base_url=config.base_url if config.provider == "openai-compatible" else None,
        api_key=api_key or "not-required",
        timeout=options.get("timeout_seconds", 60),
        max_retries=options.get("max_retries", 1),
        temperature=options.get("temperature"),
    )
