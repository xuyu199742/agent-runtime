from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from app.application.auth import Principal
from app.application.model_test import probe_draft_model, probe_saved_model
from app.infrastructure.model_secrets import ModelSecretConfigurationError
from app.transport.http.common import Audit, Catalog
from app.transport.http.models import model_out
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.dependencies import require
from app.transport.schemas.legacy import ModelIn

router = APIRouter(prefix="/api/v1/admin/models", tags=["admin-models"])
Viewer = Annotated[Principal, Depends(require("model:view"))]
Editor = Annotated[Principal, Depends(require("model:update"))]
Tester = Annotated[Principal, Depends(require("model:test"))]


@router.get("")
async def list_models(
    _user: Viewer,
    catalog: Catalog,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = None,
    enabled: bool | None = None,
    sort_by: Literal["name", "updated_at"] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
):
    models, total = await catalog.page_models(
        page, page_size, keyword, enabled, sort_by, sort_order
    )
    return {
        "items": [model_out(model) for model in models],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.post("/test-connection")
async def test_draft(body: ModelIn, user: Tester, audit: Audit, request: Request):
    result = await probe_draft_model(body.model_dump(exclude={"api_key"}), body.api_key)
    await record_action(
        audit,
        request,
        user,
        "model:test-draft",
        "model",
        None,
        {"success": result["success"], "stage": result.get("stage")},
    )
    return result


@router.get("/{model_id}")
async def detail(model_id: str, _user: Viewer, catalog: Catalog):
    return model_out(await catalog.get_model(model_id))


@router.post("", status_code=201)
async def create(body: ModelIn, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    try:
        model = await catalog.save_model(body.model_dump(exclude={"api_key"}), body.api_key)
    except ModelSecretConfigurationError:
        raise HTTPException(503, detail="模型密钥存储未配置") from None
    await record_action(
        audit, request, user, "model:create", "model", model.id, {"name": model.name}
    )
    return model_out(model)


@router.put("/{model_id}")
async def update(
    model_id: str,
    body: ModelIn,
    user: Editor,
    catalog: Catalog,
    audit: Audit,
    request: Request,
):
    try:
        model = await catalog.save_model(
            body.model_dump(exclude={"api_key"}), body.api_key, model_id
        )
    except ModelSecretConfigurationError:
        raise HTTPException(503, detail="模型密钥存储未配置") from None
    await record_action(
        audit, request, user, "model:update", "model", model.id, {"name": model.name}
    )
    return model_out(model)


@router.post("/{model_id}/test-connection")
async def test_saved(
    model_id: str,
    user: Tester,
    catalog: Catalog,
    audit: Audit,
    request: Request,
):
    model = await catalog.get_model(model_id)
    result = await probe_saved_model(model)
    await record_action(
        audit,
        request,
        user,
        "model:test",
        "model",
        model_id,
        {"success": result["success"], "stage": result.get("stage")},
    )
    return result


@router.post("/{model_id}/enable")
async def enable(model_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    model = await catalog.change_state("model", model_id, True)
    await record_action(audit, request, user, "model:enable", "model", model.id)
    return model_out(model)


@router.post("/{model_id}/disable")
async def disable(model_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    model = await catalog.change_state("model", model_id, False)
    await record_action(audit, request, user, "model:disable", "model", model.id)
    return model_out(model)


@router.post("/{model_id}/archive", status_code=204)
async def archive(model_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    await catalog.change_state("model", model_id, None)
    await record_action(audit, request, user, "model:archive", "model", model_id)
