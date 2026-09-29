from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.application.models import save_model
from app.infrastructure.database import ModelConfig
from app.infrastructure.model_secrets import ModelSecretConfigurationError
from app.transport.http.common import Db
from app.transport.schemas import ModelIn, ModelOut


def model_out(model: ModelConfig) -> ModelOut:
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
async def add_model(body: ModelIn, db: Db):
    try:
        model = await save_model(db, body.model_dump(exclude={"api_key"}), body.api_key)
    except ModelSecretConfigurationError:
        raise HTTPException(503, detail="模型密钥存储未配置") from None
    return model_out(model)


@router.get("/api/models", response_model=list[ModelOut])
async def list_models(db: Db):
    return [
        model_out(item)
        for item in (await db.scalars(select(ModelConfig).order_by(ModelConfig.name))).all()
    ]


@router.get("/api/models/{model_id}", response_model=ModelOut)
async def get_model(model_id: str, db: Db):
    model = await db.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(404, detail="模型不存在")
    return model_out(model)


@router.put("/api/models/{model_id}", response_model=ModelOut)
async def update_model(model_id: str, body: ModelIn, db: Db):
    model = await db.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(404, detail="模型不存在")
    try:
        model = await save_model(db, body.model_dump(exclude={"api_key"}), body.api_key, model)
    except ModelSecretConfigurationError:
        raise HTTPException(503, detail="模型密钥存储未配置") from None
    return model_out(model)


@router.delete("/api/models/{model_id}", status_code=204)
async def delete_model(model_id: str, db: Db):
    model = await db.get(ModelConfig, model_id)
    if model is None:
        raise HTTPException(404, detail="模型不存在")
    await db.delete(model)
    await db.commit()
