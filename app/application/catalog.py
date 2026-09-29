from dataclasses import dataclass

from app.domain.errors import InvalidConfiguration
from app.persistence.repositories.catalog import CatalogRepository


@dataclass(frozen=True)
class AgentInput:
    name: str
    description: str
    system_prompt: str
    model_id: str
    max_model_calls: int
    enabled: bool
    tool_ids: list[str]


async def save_agent(db, body: AgentInput, agent=None):
    catalog = CatalogRepository(db)
    model = await catalog.model(body.model_id)
    if model is None or not model.enabled:
        raise InvalidConfiguration("模型不存在或未启用")
    tools = await catalog.tools(body.tool_ids)
    if len(tools) != len(set(body.tool_ids)) or any(not tool.enabled for tool in tools):
        raise InvalidConfiguration("工具不存在、重复或未启用")
    values = {
        key: getattr(body, key)
        for key in (
            "name",
            "description",
            "system_prompt",
            "model_id",
            "max_model_calls",
            "enabled",
        )
    }
    return await catalog.save_agent(values, tools, agent)


def agent_out(agent) -> dict:
    fields = (
        "id",
        "name",
        "description",
        "system_prompt",
        "model_id",
        "max_model_calls",
        "enabled",
        "created_at",
        "updated_at",
    )
    return {
        **{field: getattr(agent, field) for field in fields},
        "tool_ids": [tool.id for tool in agent.tools],
    }
