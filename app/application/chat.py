from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import Conflict, InvalidConfiguration, NotFound
from app.infrastructure.database import AgentDefinition, Message, ModelConfig, Run, Session, new_id


@dataclass(frozen=True)
class AcceptedMessage:
    message_id: str
    run_id: str


async def create_session(db: AsyncSession, agent_id: str, user_id: str) -> Session:
    agent = await db.get(AgentDefinition, agent_id)
    if agent is None or not agent.enabled:
        raise InvalidConfiguration("Agent 不存在或未启用")
    model = await db.get(ModelConfig, agent.model_id)
    if model is None or not model.enabled:
        raise InvalidConfiguration("模型不存在或未启用")
    session = Session(agent_id=agent_id, user_id=user_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def submit_message(
    db: AsyncSession, session_id: str, user_id: str, client_message_id: str, content: str
) -> AcceptedMessage:
    session = await db.get(Session, session_id)
    if session is None or session.user_id != user_id:
        raise NotFound("Session 不存在")

    async def existing() -> AcceptedMessage | None:
        row = (
            await db.execute(
                select(Message, Run)
                .join(Run, Run.message_id == Message.id)
                .where(Message.user_id == user_id, Message.client_message_id == client_message_id)
            )
        ).first()
        if row is None:
            return None
        message, run = row
        if message.session_id != session_id or message.content != content:
            raise Conflict("client_message_id 已用于其他消息")
        return AcceptedMessage(message_id=message.id, run_id=run.id)

    previous = await existing()
    if previous is not None:
        return previous

    # 同一 Session 的不同请求串行创建 Run；拿锁后再次检查幂等键。
    await db.execute(select(Session.id).where(Session.id == session_id).with_for_update())
    previous = await existing()
    if previous is not None:
        return previous

    active = await db.scalar(
        select(Run.id).where(
            Run.session_id == session_id,
            Run.status.in_(["PENDING", "RUNNING", "INTERRUPTED"]),
        )
    )
    if active is not None:
        raise Conflict("Session 中已有执行中的 Run")

    message = Message(
        id=new_id(),
        session_id=session_id,
        user_id=user_id,
        role="user",
        content=content,
        client_message_id=client_message_id,
    )
    run = Run(id=new_id(), session_id=session_id, message_id=message.id, status="PENDING")
    db.add_all([message, run])
    try:
        await db.commit()
    except IntegrityError:
        await db.rollback()
        previous = await existing()
        if previous is not None:
            return previous
        raise
    return AcceptedMessage(message_id=message.id, run_id=run.id)
