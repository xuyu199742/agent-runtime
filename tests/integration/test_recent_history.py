import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.database import AgentDefinition, Message, ModelConfig, Session
from app.persistence.repositories.conversations import ConversationRepository


async def test_repository_loads_only_recent_session_messages():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"history-model-{suffix}", provider="openai", model_name="fake"
            )
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"history-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="history-user")
            db.add(session)
            await db.flush()
            for index in range(80):
                db.add(
                    Message(
                        session_id=session.id,
                        user_id="history-user",
                        role="user",
                        content=str(index),
                        created_at=datetime.now(UTC) + timedelta(seconds=index),
                    )
                )
            await db.commit()
            recent = await ConversationRepository(db).recent_messages(
                session.id, datetime.now(UTC) + timedelta(seconds=90), 5
            )
            assert [message.content for message in recent] == [str(i) for i in range(75, 80)]
    finally:
        await engine.dispose()
