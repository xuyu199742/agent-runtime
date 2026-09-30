from dataclasses import dataclass

from app.domain.agent import ToolDefinition as RuntimeToolDefinition
from app.domain.errors import Conflict, InvalidConfiguration, NotFound
from app.persistence.repositories.catalog import CatalogRepository
from app.runtime.tools import build_tools


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

    async def public_agents(self):
        return await self.catalog.public_agents()

    async def page_agents(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        enabled=None,
        sort_by="name",
        sort_order="asc",
    ):
        return await self.catalog.page_agents(
            page, page_size, keyword, enabled, sort_by, sort_order
        )

    async def page_models(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        enabled=None,
        sort_by="name",
        sort_order="asc",
    ):
        return await self.catalog.page_models(
            page, page_size, keyword, enabled, sort_by, sort_order
        )

    async def page_tools(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        enabled=None,
        sort_by="name",
        sort_order="asc",
    ):
        return await self.catalog.page_tools(page, page_size, keyword, enabled, sort_by, sort_order)

    async def get_agent(self, agent_id: str):
        agent = await self.catalog.agent(agent_id)
        if agent is None:
            raise NotFound("Agent 不存在")
        return agent

    async def agent_revisions(self, agent_id: str):
        await self.get_agent(agent_id)
        return await self.catalog.agent_revisions(agent_id)

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

    async def test_tool(self, tool_id: str, args: dict):
        tool = await self.get_tool(tool_id)
        if not tool.enabled or tool.archived_at is not None:
            raise Conflict("Tool 未启用")
        if tool.effect_type != "READ_ONLY" or tool.policy.get("requires_approval"):
            raise Conflict("此 Tool 不允许直接测试")
        runtime_tool = build_tools(
            [
                RuntimeToolDefinition(
                    name=tool.name,
                    type=tool.type,
                    description=tool.description,
                    config=tool.config,
                    policy=tool.policy,
                )
            ]
        )[0]
        try:
            result = await runtime_tool.ainvoke(args)
        except Exception:  # noqa: BLE001 - 不向管理界面泄漏底层异常或目标地址细节
            return {"success": False, "code": "TOOL_ERROR", "message": "工具执行失败"}
        return {"success": True, "result": str(result)}

    async def delete_tool(self, tool_id: str):
        await self.catalog.delete(await self.get_tool(tool_id))

    async def change_state(self, kind: str, entity_id: str, enabled: bool | None):
        getter = {"agent": self.get_agent, "model": self.get_model, "tool": self.get_tool}[kind]
        entity = await getter(entity_id)
        if entity.archived_at is not None:
            raise Conflict("已归档配置不能修改")
        if enabled is not True and await self.catalog.active_run_uses(entity):
            raise Conflict("仍有执行中的 Run 使用该配置")
        if enabled is None:
            await self.catalog.archive(entity)
            return entity
        return await self.catalog.set_enabled(entity, enabled)


def agent_out(agent) -> dict:
    fields = (
        "id",
        "name",
        "description",
        "system_prompt",
        "model_id",
        "max_model_calls",
        "revision",
        "enabled",
        "created_at",
        "updated_at",
    )
    return {
        **{field: getattr(agent, field) for field in fields},
        "tool_ids": [tool.id for tool in agent.tools],
    }
