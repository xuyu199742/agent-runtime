import pytest

from app.domain.agent import ModelDefinition
from app.persistence.database import ModelConfig
from app.runtime.factory import build_model, resolve_model_config
from app.runtime.tools import calculate


def test_openai_compatible_model_uses_configured_endpoint():
    config = ModelConfig(
        name="local",
        provider="openai-compatible",
        model_name="qwen",
        base_url="http://localhost:8001/v1",
        api_key_encrypted=None,
        config={},
        enabled=True,
    )
    model = build_model(
        resolve_model_config(
            ModelDefinition(
                provider=config.provider,
                model_name=config.model_name,
                base_url=config.base_url,
                config=config.config,
            ),
            config.api_key_encrypted,
        )
    )
    assert model.model_name == "qwen"
    assert str(model.openai_api_base) == "http://localhost:8001/v1"
    assert model.max_tokens is None


def test_max_output_tokens_is_sent_as_model_output_limit():
    model = build_model(
        resolve_model_config(
            ModelDefinition(
                provider="openai-compatible",
                model_name="deepseek-flash",
                base_url="https://api.deepseek.com",
                config={"context_window": 1_048_576, "max_output_tokens": 393_216},
            ),
            None,
        )
    )
    assert model.max_tokens == 393_216


def test_calculator_rejects_code_execution():
    with pytest.raises(ValueError):
        calculate("__import__('os').system('echo unsafe')")
