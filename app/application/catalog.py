from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import InvalidConfiguration
from app.infrastructure.database import AgentDefinition, ModelConfig, ToolDefinition


@dataclass(frozen=True)
class AgentInput:
    name: str
    description: str
    system_prompt: str
    model_id: str
    max_steps: int
    enabled: bool
    tool_ids: list[str]


async def validate_agent_links(db: AsyncSession, body: AgentInput) -> list[ToolDefinition]:
    model = await db.get(ModelConfig, body.model_id)
    if model is None or not model.enabled:
        raise InvalidConfiguration("模型不存在或未启用")
    tools = list(
        (await db.scalars(select(ToolDefinition).where(ToolDefinition.id.in_(body.tool_ids)))).all()
    )
    if len(tools) != len(set(body.tool_ids)) or any(not tool.enabled for tool in tools):
        raise InvalidConfiguration("工具不存在、重复或未启用")
    return tools


async def save_agent(
    db: AsyncSession, body: AgentInput, agent: AgentDefinition | None = None
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


def agent_out(agent: AgentDefinition) -> dict:
    fields = (
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
    return {
        **{field: getattr(agent, field) for field in fields},
        "tool_ids": [tool.id for tool in agent.tools],
    }
