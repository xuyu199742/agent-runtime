import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.database import AgentDefinition, Message, ModelConfig, Run, Session
from app.runtime.agent import LangChainAgentRuntime
from app.runtime.checkpoint import create_checkpoint_pool, create_saver
from app.worker import retention as worker


async def test_terminal_run_checkpoint_is_pruned_after_retention(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"retention-model-{suffix}", provider="openai", model_name="fake"
            )
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"retention-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="user")
            db.add(session)
            await db.flush()
            message = Message(session_id=session.id, user_id="user", role="user", content="hi")
            db.add(message)
            await db.flush()
            run = Run(session_id=session.id, message_id=message.id, status="COMPLETED")
            db.add(run)
            await db.commit()
            run_id = run.id

        pool = create_checkpoint_pool(os.environ["TEST_CHECKPOINT_DATABASE_URL"], concurrency=1)
        async with pool:
            saver = create_saver(pool)
            await saver.setup()

            async def emit(_kind, _data):
                pass

            async def not_cancelled():
                return False

            runtime = LangChainAgentRuntime(
                FakeMessagesListChatModel(responses=[AIMessage(content="done")]), [], "", 5, saver
            )
            await runtime.run(run_id, [HumanMessage(content="hi")], emit, not_cancelled)
            async with factory() as db:
                await db.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(updated_at=datetime.now(UTC) - timedelta(hours=25))
                )
                await db.commit()
            monkeypatch.setattr(worker, "session_factory", factory)
            assert await worker.cleanup_checkpoints(saver, retention_hours=24) >= 1
            assert await saver.aget_tuple({"configurable": {"thread_id": run_id}}) is None
            async with factory() as db:
                cleaned = await db.get(Run, run_id)
                assert cleaned.checkpoint_pruned_at is not None
                assert cleaned.updated_at < datetime.now(UTC) - timedelta(hours=24)
    finally:
        await engine.dispose()
