from app.infrastructure.model_secrets import encrypt_model_key
from app.persistence.repositories.catalog import CatalogRepository


async def save_model(db, values: dict, api_key: str | None, model=None):
    encrypted_key = encrypt_model_key(api_key) if api_key is not None else None
    return await CatalogRepository(db).save_model(values, encrypted_key, model)
