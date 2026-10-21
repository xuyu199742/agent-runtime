from dataclasses import dataclass

from langchain_openai import ChatOpenAI

from app.domain.agent import ModelDefinition
from app.infrastructure.model_secrets import decrypt_model_key
from app.runtime.compatible_model import CompatibleChatOpenAI
from app.runtime.tool_names_model import ToolNameChatOpenAI


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
    max_output_tokens = options.get("max_output_tokens")
    model_class = (
        CompatibleChatOpenAI if config.provider == "openai-compatible" else ToolNameChatOpenAI
    )
    provider_options = {}
    thinking_mode = options.get("thinking_mode", "default")
    if config.provider == "openai-compatible" and thinking_mode in {"enabled", "disabled"}:
        provider_options["extra_body"] = {"thinking": {"type": thinking_mode}}
    if options.get("reasoning_effort"):
        provider_options["reasoning_effort"] = options["reasoning_effort"]
    return model_class(
        model=config.model_name,
        base_url=config.base_url if config.provider == "openai-compatible" else None,
        api_key=api_key or "not-required",
        timeout=options.get("timeout_seconds", 60),
        max_retries=options.get("max_retries", 1),
        temperature=options.get("temperature"),
        max_tokens=max_output_tokens if _positive_int(max_output_tokens) else None,
        **provider_options,
    )


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0
