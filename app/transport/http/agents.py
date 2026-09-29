from fastapi import APIRouter

from app.application.catalog import AgentInput, agent_out
from app.transport.http.common import Catalog
from app.transport.schemas import AgentIn, AgentOut

router = APIRouter()


@router.post("/api/agents", response_model=AgentOut, status_code=201)
async def add_agent(body: AgentIn, catalog: Catalog):
    return agent_out(await catalog.save_agent(AgentInput(**body.model_dump())))


@router.get("/api/agents", response_model=list[AgentOut])
async def list_agents(catalog: Catalog):
    return [agent_out(agent) for agent in await catalog.list_agents()]


@router.get("/api/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, catalog: Catalog):
    return agent_out(await catalog.get_agent(agent_id))


@router.put("/api/agents/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, body: AgentIn, catalog: Catalog):
    return agent_out(await catalog.save_agent(AgentInput(**body.model_dump()), agent_id))


@router.delete("/api/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, catalog: Catalog):
    await catalog.delete_agent(agent_id)
