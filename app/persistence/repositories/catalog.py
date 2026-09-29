from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import AgentDefinition, ModelConfig, ToolDefinition


class CatalogRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def model(self, model_id: str):
        return await self.db.get(ModelConfig, model_id)

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

    async def save_model(self, values: dict, encrypted_key: str | None, model=None):
        if model is None:
            model = ModelConfig()
            self.db.add(model)
        for key, value in values.items():
            setattr(model, key, value)
        if encrypted_key is not None:
            model.api_key_encrypted = encrypted_key
        await self.db.commit()
        await self.db.refresh(model)
        return model
