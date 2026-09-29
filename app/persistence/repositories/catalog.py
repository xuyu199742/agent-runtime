from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.model_secrets import encrypt_model_key
from app.persistence.database import AgentDefinition, ModelConfig, ToolDefinition


class CatalogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def model(self, model_id: str):
        return await self.db.get(ModelConfig, model_id)

    async def agent(self, agent_id: str):
        return await self.db.get(AgentDefinition, agent_id)

    async def tool(self, tool_id: str):
        return await self.db.get(ToolDefinition, tool_id)

    async def list_agents(self):
        return list(
            (await self.db.scalars(select(AgentDefinition).order_by(AgentDefinition.name))).all()
        )

    async def list_models(self):
        return list((await self.db.scalars(select(ModelConfig).order_by(ModelConfig.name))).all())

    async def list_tools(self):
        return list(
            (await self.db.scalars(select(ToolDefinition).order_by(ToolDefinition.name))).all()
        )

    async def save_tool(self, values: dict, tool=None):
        if tool is None:
            tool = ToolDefinition()
            self.db.add(tool)
        for key, value in values.items():
            setattr(tool, key, value)
        await self.db.commit()
        await self.db.refresh(tool)
        return tool

    async def delete(self, entity) -> None:
        await self.db.delete(entity)
        await self.db.commit()

    async def tools(self, tool_ids: list[str]):
        return list(
            (
                await self.db.scalars(select(ToolDefinition).where(ToolDefinition.id.in_(tool_ids)))
            ).all()
        )

    async def save_agent(self, values: dict, tools: list, agent=None):
        if agent is None:
            agent = AgentDefinition()
            self.db.add(agent)
        for key, value in values.items():
            setattr(agent, key, value)
        agent.tools = tools
        await self.db.commit()
        await self.db.refresh(agent)
        return agent

    async def save_model(self, values: dict, api_key: str | None, model=None):
        if model is None:
            model = ModelConfig()
            self.db.add(model)
        for key, value in values.items():
            setattr(model, key, value)
        if api_key is not None:
            model.api_key_encrypted = encrypt_model_key(api_key)
        await self.db.commit()
        await self.db.refresh(model)
        return model
