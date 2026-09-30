from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.model_secrets import encrypt_model_key
from app.persistence.database import (
    AgentDefinition,
    AgentTool,
    ModelConfig,
    Run,
    Session,
    ToolDefinition,
)


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

    async def public_agents(self):
        return list(
            (
                await self.db.scalars(
                    select(AgentDefinition)
                    .where(AgentDefinition.enabled.is_(True), AgentDefinition.archived_at.is_(None))
                    .order_by(AgentDefinition.name)
                )
            ).all()
        )

    async def list_models(self):
        return list((await self.db.scalars(select(ModelConfig).order_by(ModelConfig.name))).all())

    async def list_tools(self):
        return list(
            (await self.db.scalars(select(ToolDefinition).order_by(ToolDefinition.name))).all()
        )

    async def page_agents(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        enabled: bool | None = None,
        sort_by: str = "name",
        sort_order: str = "asc",
    ):
        return await self._page(
            AgentDefinition, page, page_size, keyword, enabled, sort_by, sort_order
        )

    async def page_models(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        enabled: bool | None = None,
        sort_by: str = "name",
        sort_order: str = "asc",
    ):
        return await self._page(ModelConfig, page, page_size, keyword, enabled, sort_by, sort_order)

    async def page_tools(
        self,
        page: int,
        page_size: int,
        keyword: str | None,
        enabled: bool | None = None,
        sort_by: str = "name",
        sort_order: str = "asc",
    ):
        return await self._page(
            ToolDefinition, page, page_size, keyword, enabled, sort_by, sort_order
        )

    async def _page(
        self,
        entity,
        page: int,
        page_size: int,
        keyword: str | None,
        enabled: bool | None,
        sort_by: str,
        sort_order: str,
    ):
        statement = select(entity).where(entity.archived_at.is_(None))
        if keyword:
            statement = statement.where(entity.name.ilike(f"%{keyword}%"))
        if enabled is not None:
            statement = statement.where(entity.enabled.is_(enabled))
        total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
        sort_column = {"name": entity.name, "updated_at": entity.updated_at}[sort_by]
        ordering = sort_column.desc() if sort_order == "desc" else sort_column.asc()
        rows = (
            await self.db.scalars(
                statement.order_by(ordering, entity.id)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), total or 0

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

    async def active_run_uses(self, entity) -> bool:
        statement = (
            select(Run.id)
            .join(Session, Session.id == Run.session_id)
            .join(AgentDefinition, AgentDefinition.id == Session.agent_id)
            .where(Run.status.in_(["PENDING", "RUNNING"]))
        )
        if isinstance(entity, AgentDefinition):
            statement = statement.where(AgentDefinition.id == entity.id)
        elif isinstance(entity, ModelConfig):
            statement = statement.where(AgentDefinition.model_id == entity.id)
        else:
            statement = statement.join(AgentTool, AgentTool.agent_id == AgentDefinition.id)
            statement = statement.where(AgentTool.tool_id == entity.id)
        return await self.db.scalar(statement.limit(1)) is not None

    async def set_enabled(self, entity, enabled: bool):
        entity.enabled = enabled
        await self.db.commit()
        await self.db.refresh(entity)
        return entity

    async def archive(self, entity) -> None:
        entity.enabled = False
        entity.archived_at = datetime.now(UTC)
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
        if agent.id is not None:
            agent.revision += 1
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
