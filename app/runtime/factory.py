from dataclasses import dataclass

from langchain_openai import ChatOpenAI

from app.domain.agent import ModelDefinition
from app.infrastructure.model_secrets import decrypt_model_key


@dataclass(frozen=True)
class ModelRuntimeConfig:
    definition: ModelDefinition
    credential: str | None = None


def resolve_model_config(definition: ModelDefinition, encrypted_key: str | None):
    return ModelRuntimeConfig(
        definition=definition,
        credential=decrypt_model_key(encrypted_key) if encrypted_key else None,
    )


def build_model(runtime_config: ModelRuntimeConfig) -> ChatOpenAI:
    config = runtime_config.definition
    if not config.enabled or config.provider not in {"openai", "openai-compatible"}:
        raise ValueError("模型配置不可用")
    if config.provider == "openai-compatible" and not config.base_url:
        raise ValueError("OpenAI-compatible 模型必须配置 base_url")
    api_key = runtime_config.credential
    if not api_key and config.provider == "openai":
        raise ValueError("模型尚未配置凭证")
    options = config.config or {}
    return ChatOpenAI(
        model=config.model_name,
        base_url=config.base_url if config.provider == "openai-compatible" else None,
        api_key=api_key or "not-required",
        timeout=options.get("timeout_seconds", 60),
        max_retries=options.get("max_retries", 1),
        temperature=options.get("temperature"),
    )
