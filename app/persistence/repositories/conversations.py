from datetime import UTC, datetime

from sqlalchemy import func, select, tuple_
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import AgentDefinition, Message, ModelConfig, Run, Session, new_id
from app.persistence.execution_spec import freeze_execution_spec


class ConversationRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def agent(self, agent_id: str):
        return await self.db.get(AgentDefinition, agent_id)

    async def model(self, model_id: str):
        return await self.db.get(ModelConfig, model_id)

    async def session(self, session_id: str):
        return await self.db.get(Session, session_id)

    async def list_sessions(self, user_id: str | None, page: int, page_size: int):
        conditions = [Session.archived_at.is_(None)]
        if user_id is not None:
            conditions.append(Session.user_id == user_id)
        total = await self.db.scalar(select(func.count()).select_from(Session).where(*conditions))
        last_message = (
            select(Message.content)
            .where(Message.session_id == Session.id)
            .order_by(Message.created_at.desc(), Message.id.desc())
            .limit(1)
            .scalar_subquery()
        )
        rows = (
            await self.db.execute(
                select(Session, AgentDefinition.name, last_message)
                .join(AgentDefinition, AgentDefinition.id == Session.agent_id)
                .where(*conditions)
                .order_by(Session.last_active_at.desc(), Session.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return rows, total or 0

    async def page_messages(self, session_id: str, before: str | None, limit: int):
        statement = select(Message).where(Message.session_id == session_id)
        if before:
            cursor = await self.db.get(Message, before)
            if cursor is None or cursor.session_id != session_id:
                return []
            statement = statement.where(
                tuple_(Message.created_at, Message.id) < (cursor.created_at, cursor.id)
            )
        rows = (
            await self.db.scalars(
                statement.order_by(Message.created_at.desc(), Message.id.desc()).limit(limit)
            )
        ).all()
        return list(reversed(rows))

    async def statistics(self, session_id: str) -> dict:
        message_count = await self.db.scalar(
            select(func.count()).select_from(Message).where(Message.session_id == session_id)
        )
        run_count = await self.db.scalar(
            select(func.count()).select_from(Run).where(Run.session_id == session_id)
        )
        return {
            "message_count": message_count or 0,
            "run_count": run_count or 0,
            "artifact_count": 0,
        }

    async def update_title(self, session: Session, title: str) -> Session:
        session.title = title
        await self.db.commit()
        return session

    async def archive(self, session: Session) -> None:
        session.archived_at = datetime.now(UTC)
        await self.db.commit()

    async def recent_messages(self, session_id: str, before, limit: int):
        rows = (
            await self.db.scalars(
                select(Message)
                .where(Message.session_id == session_id, Message.created_at <= before)
                .order_by(Message.created_at.desc(), Message.id.desc())
                .limit(limit)
            )
        ).all()
        return list(reversed(rows))

    async def create_session(self, agent_id: str, user_id: str):
        session = Session(agent_id=agent_id, user_id=user_id)
        self.db.add(session)
        await self.db.commit()
        await self.db.refresh(session)
        return session

    async def existing_submission(self, user_id: str, client_message_id: str):
        return (
            await self.db.execute(
                select(Message, Run)
                .join(Run, Run.message_id == Message.id)
                .where(
                    Message.user_id == user_id,
                    Message.client_message_id == client_message_id,
                    Run.parent_run_id.is_(None),
                )
            )
        ).first()

    async def lock_session(self, session_id: str) -> None:
        await self.db.execute(select(Session.id).where(Session.id == session_id).with_for_update())

    async def has_active_run(self, session_id: str) -> bool:
        return (
            await self.db.scalar(
                select(Run.id).where(
                    Run.session_id == session_id, Run.status.in_(["PENDING", "RUNNING"])
                )
            )
            is not None
        )

    async def create_submission(
        self, session_id: str, user_id: str, client_message_id: str, content: str
    ) -> tuple[str, str] | None:
        message = Message(
            id=new_id(),
            session_id=session_id,
            user_id=user_id,
            role="user",
            content=content,
            client_message_id=client_message_id,
        )
        session = await self.db.get(Session, session_id)
        agent = await self.db.get(AgentDefinition, session.agent_id)
        model = await self.db.get(ModelConfig, agent.model_id)
        spec = freeze_execution_spec(agent, model)
        run = Run(
            id=new_id(),
            session_id=session_id,
            message_id=message.id,
            status="PENDING",
            execution_spec_id=spec.id,
            runtime_version=spec.runtime_version,
        )
        session.last_active_at = datetime.now(UTC)
        if not session.title:
            session.title = content[:100]
        self.db.add_all([message, spec, run])
        try:
            await self.db.commit()
        except IntegrityError:
            await self.db.rollback()
            return None
        return message.id, run.id
