import pytest
from cryptography.fernet import Fernet

from app.domain.agent import ModelDefinition
from app.infrastructure.model_secrets import decrypt_model_key, encrypt_model_key
from app.runtime.factory import build_model, resolve_model_config
from app.transport.schemas import ModelIn, ModelOut


def test_model_key_is_encrypted_and_not_returned(monkeypatch):
    monkeypatch.setenv("MODEL_SECRET_KEY", Fernet.generate_key().decode())
    token = encrypt_model_key("private-key")
    assert "private-key" not in token
    assert decrypt_model_key(token) == "private-key"
    model = build_model(
        resolve_model_config(ModelDefinition(provider="openai", model_name="gpt-test"), token)
    )
    assert model.openai_api_key.get_secret_value() == "private-key"

    body = ModelIn(name="test", provider="openai", model_name="gpt-test", api_key="private-key")
    assert body.api_key == "private-key"
    response = ModelOut(
        id="1", name="test", provider="openai", model_name="gpt-test", has_api_key=True
    )
    assert "api_key" not in response.model_dump()
    assert response.has_api_key is True


def test_missing_master_key_rejects_secret_write(monkeypatch):
    monkeypatch.setenv("MODEL_SECRET_KEY", "")
    with pytest.raises(ValueError):
        encrypt_model_key("private-key")


def test_openai_model_without_database_credential_is_rejected():
    with pytest.raises(ValueError, match="模型尚未配置凭证"):
        build_model(
            resolve_model_config(ModelDefinition(provider="openai", model_name="gpt-test"), None)
        )
