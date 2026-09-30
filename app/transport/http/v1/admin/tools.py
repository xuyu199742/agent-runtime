from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.application.auth import Principal
from app.transport.http.common import Audit, Catalog
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.dependencies import require
from app.transport.schemas.legacy import ToolIn

router = APIRouter(prefix="/api/v1/admin/tools", tags=["admin-tools"])
Viewer = Annotated[Principal, Depends(require("tool:view"))]
Editor = Annotated[Principal, Depends(require("tool:update"))]


@router.get("")
async def list_tools(
    _user: Viewer,
    catalog: Catalog,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = None,
    enabled: bool | None = None,
    sort_by: Literal["name", "updated_at"] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
):
    tools, total = await catalog.page_tools(page, page_size, keyword, enabled, sort_by, sort_order)
    return {"items": tools, "page": page, "page_size": page_size, "total": total}


@router.get("/{tool_id}")
async def detail(tool_id: str, _user: Viewer, catalog: Catalog):
    return await catalog.get_tool(tool_id)


@router.post("", status_code=201)
async def create(body: ToolIn, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    tool = await catalog.save_tool(body.model_dump())
    await record_action(audit, request, user, "tool:create", "tool", tool.id, {"name": tool.name})
    return tool


@router.put("/{tool_id}")
async def update(
    tool_id: str,
    body: ToolIn,
    user: Editor,
    catalog: Catalog,
    audit: Audit,
    request: Request,
):
    tool = await catalog.save_tool(body.model_dump(), tool_id)
    await record_action(audit, request, user, "tool:update", "tool", tool.id, {"name": tool.name})
    return tool


@router.post("/{tool_id}/enable")
async def enable(tool_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    tool = await catalog.change_state("tool", tool_id, True)
    await record_action(audit, request, user, "tool:enable", "tool", tool.id)
    return tool


@router.post("/{tool_id}/disable")
async def disable(tool_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    tool = await catalog.change_state("tool", tool_id, False)
    await record_action(audit, request, user, "tool:disable", "tool", tool.id)
    return tool


@router.post("/{tool_id}/archive", status_code=204)
async def archive(tool_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    await catalog.change_state("tool", tool_id, None)
    await record_action(audit, request, user, "tool:archive", "tool", tool_id)
