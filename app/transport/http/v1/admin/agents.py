from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.application.auth import Principal
from app.application.catalog import AgentInput, agent_out
from app.transport.http.common import Audit, Catalog
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.dependencies import require
from app.transport.schemas.legacy import AgentIn

router = APIRouter(prefix="/api/v1/admin/agents", tags=["admin-agents"])
Viewer = Annotated[Principal, Depends(require("agent:view"))]
Editor = Annotated[Principal, Depends(require("agent:update"))]


@router.get("")
async def list_agents(
    _user: Viewer,
    catalog: Catalog,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    keyword: str | None = None,
    enabled: bool | None = None,
    sort_by: Literal["name", "updated_at"] = "name",
    sort_order: Literal["asc", "desc"] = "asc",
):
    agents, total = await catalog.page_agents(
        page, page_size, keyword, enabled, sort_by, sort_order
    )
    return {
        "items": [agent_out(agent) for agent in agents],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{agent_id}")
async def detail(agent_id: str, _user: Viewer, catalog: Catalog):
    return agent_out(await catalog.get_agent(agent_id))


@router.post("", status_code=201)
async def create(body: AgentIn, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    agent = await catalog.save_agent(AgentInput(**body.model_dump()))
    await record_action(
        audit, request, user, "agent:create", "agent", agent.id, {"name": agent.name}
    )
    return agent_out(agent)


@router.put("/{agent_id}")
async def update(
    agent_id: str,
    body: AgentIn,
    user: Editor,
    catalog: Catalog,
    audit: Audit,
    request: Request,
):
    agent = await catalog.save_agent(AgentInput(**body.model_dump()), agent_id)
    await record_action(
        audit, request, user, "agent:update", "agent", agent.id, {"name": agent.name}
    )
    return agent_out(agent)


@router.post("/{agent_id}/enable")
async def enable(agent_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    agent = await catalog.change_state("agent", agent_id, True)
    await record_action(audit, request, user, "agent:enable", "agent", agent.id)
    return agent_out(agent)


@router.post("/{agent_id}/disable")
async def disable(agent_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    agent = await catalog.change_state("agent", agent_id, False)
    await record_action(audit, request, user, "agent:disable", "agent", agent.id)
    return agent_out(agent)


@router.post("/{agent_id}/archive", status_code=204)
async def archive(agent_id: str, user: Editor, catalog: Catalog, audit: Audit, request: Request):
    await catalog.change_state("agent", agent_id, None)
    await record_action(audit, request, user, "agent:archive", "agent", agent_id)
