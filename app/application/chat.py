from dataclasses import dataclass

from app.domain.errors import Conflict, InvalidConfiguration, NotFound
from app.persistence.repositories.conversations import ConversationRepository


@dataclass(frozen=True)
class AcceptedMessage:
    message_id: str
    run_id: str


async def create_session(db, agent_id: str, user_id: str):
    conversations = ConversationRepository(db)
    agent = await conversations.agent(agent_id)
    if agent is None or not agent.enabled:
        raise InvalidConfiguration("Agent 不存在或未启用")
    model = await conversations.model(agent.model_id)
    if model is None or not model.enabled:
        raise InvalidConfiguration("模型不存在或未启用")
    return await conversations.create_session(agent_id, user_id)


async def submit_message(
    db, session_id: str, user_id: str, client_message_id: str, content: str
) -> AcceptedMessage:
    conversations = ConversationRepository(db)
    session = await conversations.session(session_id)
    if session is None or session.user_id != user_id:
        raise NotFound("Session 不存在")

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

    created = await conversations.create_submission(session_id, user_id, client_message_id, content)
    if created is None:
        existing = await previous()
        if existing is not None:
            return existing
        raise Conflict("消息提交冲突")
    return AcceptedMessage(message_id=created[0], run_id=created[1])
