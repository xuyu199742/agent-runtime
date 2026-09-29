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


def test_calculator_rejects_code_execution():
    with pytest.raises(ValueError):
        calculate("__import__('os').system('echo unsafe')")
