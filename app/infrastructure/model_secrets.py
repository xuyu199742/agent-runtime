from cryptography.fernet import Fernet, InvalidToken

from app.config import Settings


class ModelSecretConfigurationError(ValueError):
    pass


def _cipher() -> Fernet:
    key = Settings().model_secret_key
    if not key:
        raise ModelSecretConfigurationError("未配置 MODEL_SECRET_KEY")
    try:
        return Fernet(key.encode())
    except (ValueError, TypeError) as exc:
        raise ModelSecretConfigurationError("MODEL_SECRET_KEY 格式无效") from exc


def encrypt_model_key(value: str) -> str:
    if not value:
        raise ValueError("模型密钥不能为空")
    return _cipher().encrypt(value.encode()).decode()


def decrypt_model_key(token: str) -> str:
    try:
        return _cipher().decrypt(token.encode()).decode()
    except InvalidToken as exc:
        raise ValueError("模型密钥无法解密") from exc
