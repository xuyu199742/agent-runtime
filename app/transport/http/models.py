from fastapi import APIRouter, HTTPException

from app.infrastructure.model_secrets import ModelSecretConfigurationError
from app.transport.http.common import Catalog
from app.transport.schemas import ModelIn, ModelOut


def model_out(model) -> ModelOut:
    return ModelOut(
        id=model.id,
        name=model.name,
        provider=model.provider,
        model_name=model.model_name,
        base_url=model.base_url,
        config=model.config,
        enabled=model.enabled,
        has_api_key=bool(model.api_key_encrypted),
    )


router = APIRouter()


@router.post("/api/models", response_model=ModelOut, status_code=201)
async def add_model(body: ModelIn, catalog: Catalog):
    try:
        model = await catalog.save_model(body.model_dump(exclude={"api_key"}), body.api_key)
    except ModelSecretConfigurationError:
        raise HTTPException(503, detail="模型密钥存储未配置") from None
    return model_out(model)


@router.get("/api/models", response_model=list[ModelOut])
async def list_models(catalog: Catalog):
    return [model_out(item) for item in await catalog.list_models()]


@router.get("/api/models/{model_id}", response_model=ModelOut)
async def get_model(model_id: str, catalog: Catalog):
    return model_out(await catalog.get_model(model_id))


@router.put("/api/models/{model_id}", response_model=ModelOut)
async def update_model(model_id: str, body: ModelIn, catalog: Catalog):
    try:
        model = await catalog.save_model(
            body.model_dump(exclude={"api_key"}), body.api_key, model_id
        )
    except ModelSecretConfigurationError:
        raise HTTPException(503, detail="模型密钥存储未配置") from None
    return model_out(model)


@router.delete("/api/models/{model_id}", status_code=204)
async def delete_model(model_id: str, catalog: Catalog):
    await catalog.delete_model(model_id)
