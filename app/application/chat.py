from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import AgentDefinition, Message, ModelConfig, Run, Session, new_id
from app.transport.schemas import MessageAccepted, MessageIn


async def create_session(db: AsyncSession, agent_id: str, user_id: str) -> Session:
    agent = await db.get(AgentDefinition, agent_id)
    if agent is None or not agent.enabled:
        raise HTTPException(422, detail="Agent 不存在或未启用")
    model = await db.get(ModelConfig, agent.model_id)
    if model is None or not model.enabled:
        raise HTTPException(422, detail="模型不存在或未启用")
    session = Session(agent_id=agent_id, user_id=user_id)
    db.add(session)
    await db.commit()
    await db.refresh(session)
    return session


async def submit_message(
    db: AsyncSession, session_id: str, user_id: str, body: MessageIn
) -> MessageAccepted:
    session = await db.get(Session, session_id)
    if session is None or session.user_id != user_id:
        raise HTTPException(404, detail="Session 不存在")

    async def existing() -> MessageAccepted | None:
        row = (
            await db.execute(
                select(Message, Run)
                .join(Run, Run.message_id == Message.id)
                .where(
                    Message.user_id == user_id, Message.client_message_id == body.client_message_id
                )
            )
        ).first()
        if row is None:
            return None
        message, run = row
        if message.session_id != session_id or message.content != body.content:
            raise HTTPException(409, detail="client_message_id 已用于其他消息")
        return MessageAccepted(message_id=message.id, run_id=run.id)

    previous = await existing()
    if previous is not None:
        return previous

    message = Message(
        id=new_id(),
        session_id=session_id,
        user_id=user_id,
        role="user",
        content=body.content,
        client_message_id=body.client_message_id,
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
    return MessageAccepted(message_id=message.id, run_id=run.id)
