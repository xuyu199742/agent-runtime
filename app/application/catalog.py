from dataclasses import dataclass

from app.domain.errors import InvalidConfiguration, NotFound
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


class CatalogService:
    def __init__(self, catalog: CatalogRepository) -> None:
        self.catalog = catalog

    async def save_agent(self, body: AgentInput, agent_id: str | None = None):
        agent = await self.get_agent(agent_id) if agent_id else None
        return await self._save_agent(body, agent)

    async def _save_agent(self, body: AgentInput, agent=None):
        catalog = self.catalog
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

    async def list_agents(self):
        return await self.catalog.list_agents()

    async def get_agent(self, agent_id: str):
        agent = await self.catalog.agent(agent_id)
        if agent is None:
            raise NotFound("Agent 不存在")
        return agent

    async def delete_agent(self, agent_id: str):
        await self.catalog.delete(await self.get_agent(agent_id))

    async def save_model(self, values: dict, api_key: str | None, model_id=None):
        model = await self.get_model(model_id) if model_id else None
        return await self.catalog.save_model(values, api_key, model)

    async def list_models(self):
        return await self.catalog.list_models()

    async def get_model(self, model_id: str):
        model = await self.catalog.model(model_id)
        if model is None:
            raise NotFound("模型不存在")
        return model

    async def delete_model(self, model_id: str):
        await self.catalog.delete(await self.get_model(model_id))

    async def save_tool(self, values: dict, tool_id=None):
        tool = await self.get_tool(tool_id) if tool_id else None
        return await self.catalog.save_tool(values, tool)

    async def list_tools(self):
        return await self.catalog.list_tools()

    async def get_tool(self, tool_id: str):
        tool = await self.catalog.tool(tool_id)
        if tool is None:
            raise NotFound("工具不存在")
        return tool

    async def delete_tool(self, tool_id: str):
        await self.catalog.delete(await self.get_tool(tool_id))


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
