from fastapi import APIRouter, HTTPException
from sqlalchemy import select

from app.application.catalog import AgentInput, agent_out, save_agent
from app.persistence.database import AgentDefinition
from app.transport.http.common import Db
from app.transport.schemas import AgentIn, AgentOut

router = APIRouter()


@router.post("/api/agents", response_model=AgentOut, status_code=201)
async def add_agent(body: AgentIn, db: Db):
    return agent_out(await save_agent(db, AgentInput(**body.model_dump())))


@router.get("/api/agents", response_model=list[AgentOut])
async def list_agents(db: Db):
    return [
        agent_out(agent)
        for agent in (
            await db.scalars(select(AgentDefinition).order_by(AgentDefinition.name))
        ).all()
    ]


@router.get("/api/agents/{agent_id}", response_model=AgentOut)
async def get_agent(agent_id: str, db: Db):
    agent = await db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(404, detail="Agent 不存在")
    return agent_out(agent)


@router.put("/api/agents/{agent_id}", response_model=AgentOut)
async def update_agent(agent_id: str, body: AgentIn, db: Db):
    agent = await db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(404, detail="Agent 不存在")
    return agent_out(await save_agent(db, AgentInput(**body.model_dump()), agent))


@router.delete("/api/agents/{agent_id}", status_code=204)
async def delete_agent(agent_id: str, db: Db):
    agent = await db.get(AgentDefinition, agent_id)
    if agent is None:
        raise HTTPException(404, detail="Agent 不存在")
    await db.delete(agent)
    await db.commit()
