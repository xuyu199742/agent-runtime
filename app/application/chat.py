from dataclasses import dataclass

from app.domain.errors import Conflict, InvalidConfiguration, NotFound
from app.persistence.repositories.conversations import ConversationRepository


@dataclass(frozen=True)
class AcceptedMessage:
    message_id: str
    run_id: str


class ConversationService:
    def __init__(self, conversations: ConversationRepository) -> None:
        self.conversations = conversations

    async def create_session(self, agent_id: str, user_id: str):
        conversations = self.conversations
        agent = await conversations.agent(agent_id)
        if agent is None or not agent.enabled or agent.archived_at is not None:
            raise InvalidConfiguration("Agent 不存在或未启用")
        model = await conversations.model(agent.model_id)
        if model is None or not model.enabled or model.archived_at is not None:
            raise InvalidConfiguration("模型不存在或未启用")
        return await conversations.create_session(agent_id, user_id)

    async def get_session(self, session_id: str, user_id: str):
        session = await self.conversations.session(session_id)
        if session is None or session.user_id != user_id or session.archived_at is not None:
            raise NotFound("Session 不存在")
        return session

    async def list_sessions(self, user_id: str | None, page: int, page_size: int):
        return await self.conversations.list_sessions(user_id, page, page_size)

    async def admin_session(self, session_id: str):
        session = await self.conversations.session(session_id)
        if session is None:
            raise NotFound("Conversation 不存在")
        return session

    async def admin_messages(self, session_id: str, before: str | None, limit: int):
        await self.admin_session(session_id)
        return await self.conversations.page_messages(session_id, before, limit)

    async def admin_statistics(self, session_id: str):
        await self.admin_session(session_id)
        return await self.conversations.statistics(session_id)

    async def agent_name(self, agent_id: str) -> str:
        agent = await self.conversations.agent(agent_id)
        return agent.name

    async def messages(self, session_id: str, user_id: str, before: str | None, limit: int):
        await self.get_session(session_id, user_id)
        return await self.conversations.page_messages(session_id, before, limit)

    async def update_title(self, session_id: str, user_id: str, title: str):
        session = await self.get_session(session_id, user_id)
        return await self.conversations.update_title(session, title)

    async def archive(self, session_id: str, user_id: str) -> None:
        session = await self.get_session(session_id, user_id)
        if await self.conversations.has_active_run(session_id):
            raise Conflict("执行中的会话不能归档")
        await self.conversations.archive(session)

    async def submit_message(
        self, session_id: str, user_id: str, client_message_id: str, content: str
    ) -> AcceptedMessage:
        conversations = self.conversations
        await self.get_session(session_id, user_id)

        async def previous() -> AcceptedMessage | None:
            row = await conversations.existing_submission(user_id, client_message_id)
            if row is None:
                return None
            message, run = row
            if message.session_id != session_id or message.content != content:
                raise Conflict("client_message_id 已用于其他消息")
            return AcceptedMessage(message_id=message.id, run_id=run.id)

        existing = await previous()
        if existing is not None:
            return existing

        # 同一 Session 的新请求串行创建 Run；拿锁后再次检查幂等键。
        await conversations.lock_session(session_id)
        existing = await previous()
        if existing is not None:
            return existing
        if await conversations.has_active_run(session_id):
            raise Conflict("Session 中已有执行中的 Run")

        created = await conversations.create_submission(
            session_id, user_id, client_message_id, content
        )
        if created is None:
            existing = await previous()
            if existing is not None:
                return existing
            raise Conflict("消息提交冲突")
        return AcceptedMessage(message_id=created[0], run_id=created[1])
