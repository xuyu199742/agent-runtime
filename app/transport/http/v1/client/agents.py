from fastapi import APIRouter, HTTPException

from app.transport.http.common import Catalog
from app.transport.http.v1.dependencies import CurrentUser
from app.transport.schemas.client import PublicAgent

router = APIRouter(prefix="/api/v1/client/agents", tags=["client-agents"])


def public_agent(agent) -> PublicAgent:
    return PublicAgent(id=agent.id, name=agent.name, description=agent.description)


@router.get("", response_model=list[PublicAgent])
async def list_agents(_user: CurrentUser, catalog: Catalog):
    return [public_agent(agent) for agent in await catalog.public_agents()]


@router.get("/{agent_id}", response_model=PublicAgent)
async def get_agent(agent_id: str, _user: CurrentUser, catalog: Catalog):
    agent = await catalog.get_agent(agent_id)
    if not agent.enabled or agent.archived_at is not None:
        raise HTTPException(404, detail="Agent 不存在")
    return public_agent(agent)
