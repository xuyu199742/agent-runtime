from typing import Annotated, Literal
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request
from pydantic import BaseModel, Field

from app.application.auth import Principal
from app.application.catalog import AgentInput, agent_out
from app.transport.http.common import Audit, Catalog, Conversation
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.approval_actions import queue_resolved_run
from app.transport.http.v1.dependencies import require
from app.transport.schemas.legacy import AgentIn

router = APIRouter(prefix="/api/v1/admin/agents", tags=["admin-agents"])
Viewer = Annotated[Principal, Depends(require("agent:view"))]
Editor = Annotated[Principal, Depends(require("agent:update"))]
Tester = Annotated[Principal, Depends(require("agent:test"))]


class AgentTestIn(BaseModel):
    content: str = Field(min_length=1, max_length=100000)


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


@router.get("/{agent_id}/revisions")
async def revisions(agent_id: str, _user: Viewer, catalog: Catalog):
    rows = await catalog.agent_revisions(agent_id)
    return [
        {
            "id": row.id,
            "revision": row.revision,
            "snapshot": row.snapshot,
            "created_at": row.created_at,
        }
        for row in rows
    ]


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


@router.post("/{agent_id}/test", status_code=202)
async def test_agent(
    agent_id: str,
    body: AgentTestIn,
    user: Tester,
    conversation: Conversation,
    audit: Audit,
    request: Request,
):
    session = await conversation.create_session(agent_id, user.id)
    accepted = await conversation.submit_message(
        session.id, user.id, str(uuid4()), body.content, origin="ADMIN_TEST"
    )
    await queue_resolved_run(request, accepted.run_id)
    await record_action(audit, request, user, "agent:test", "agent", agent_id)
    return {"conversation_id": session.id, "run_id": accepted.run_id, "status": "PENDING"}
