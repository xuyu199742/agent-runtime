from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import ModelConfig
from app.infrastructure.model_secrets import encrypt_model_key


async def save_model(
    db: AsyncSession, values: dict, api_key: str | None, model: ModelConfig | None = None
) -> ModelConfig:
    if model is None:
        model = ModelConfig()
        db.add(model)
    for key, value in values.items():
        setattr(model, key, value)
    if api_key is not None:
        model.api_key_encrypted = encrypt_model_key(api_key)
    await db.commit()
    await db.refresh(model)
    return model
