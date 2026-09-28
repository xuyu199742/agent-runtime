from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import AgentDefinition, ModelConfig, ToolDefinition
from app.transport.schemas import AgentIn, AgentOut


async def validate_agent_links(db: AsyncSession, body: AgentIn) -> list[ToolDefinition]:
    model = await db.get(ModelConfig, body.model_id)
    if model is None or not model.enabled:
        raise HTTPException(422, detail="模型不存在或未启用")
    tools = list(
        (await db.scalars(select(ToolDefinition).where(ToolDefinition.id.in_(body.tool_ids)))).all()
    )
    if len(tools) != len(set(body.tool_ids)) or any(not tool.enabled for tool in tools):
        raise HTTPException(422, detail="工具不存在、重复或未启用")
    return tools


async def save_agent(
    db: AsyncSession, body: AgentIn, agent: AgentDefinition | None = None
) -> AgentDefinition:
    tools = await validate_agent_links(db, body)
    if agent is None:
        agent = AgentDefinition()
        db.add(agent)
    for field in ("name", "description", "system_prompt", "model_id", "max_steps", "enabled"):
        setattr(agent, field, getattr(body, field))
    agent.tools = tools
    await db.commit()
    await db.refresh(agent)
    return agent


def agent_out(agent: AgentDefinition) -> AgentOut:
    return AgentOut.model_validate(
        {
            **{
                field: getattr(agent, field)
                for field in (
                    "id",
                    "name",
                    "description",
                    "system_prompt",
                    "model_id",
                    "max_steps",
                    "enabled",
                    "created_at",
                    "updated_at",
                )
            },
            "tool_ids": [tool.id for tool in agent.tools],
        }
    )
