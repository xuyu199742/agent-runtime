from sqlalchemy import func, select

from app.persistence.database import Artifact, Message, Run, Session


class ArtifactRepository:
    def __init__(self, db):
        self.db = db

    async def save(self, values: dict):
        artifact = Artifact(**values)
        self.db.add(artifact)
        await self.db.commit()
        await self.db.refresh(artifact)
        return artifact

    async def get(self, artifact_id: str):
        return await self.db.get(Artifact, artifact_id)

    async def visible(self, artifact_id: str, user_id: str):
        return await self.db.scalar(
            select(Artifact)
            .join(Session, Session.id == Artifact.conversation_id)
            .where(Artifact.id == artifact_id, Session.user_id == user_id)
        )

    async def page_conversation(self, conversation_id: str, page: int, page_size: int):
        statement = select(Artifact).where(Artifact.conversation_id == conversation_id)
        return await self._page(statement, page, page_size)

    async def page_run(self, run_id: str, page: int, page_size: int):
        statement = select(Artifact).where(Artifact.run_id == run_id)
        return await self._page(statement, page, page_size)

    async def page_admin(self, page: int, page_size: int, user_id: str | None):
        statement = select(Artifact)
        if user_id is not None:
            statement = statement.join(Session, Session.id == Artifact.conversation_id)
            statement = statement.where(Session.user_id == user_id)
        return await self._page(statement, page, page_size)

    async def _page(self, statement, page: int, page_size: int):
        total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (
            await self.db.scalars(
                statement.order_by(Artifact.created_at.desc(), Artifact.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), total or 0

    async def validate_links(
        self, conversation_id: str, run_id: str | None, message_id: str | None
    ):
        session = await self.db.get(Session, conversation_id)
        if session is None:
            return False
        if run_id is not None:
            run = await self.db.get(Run, run_id)
            if run is None or run.session_id != conversation_id:
                return False
        if message_id is not None:
            message = await self.db.get(Message, message_id)
            if message is None or message.session_id != conversation_id:
                return False
        return True
