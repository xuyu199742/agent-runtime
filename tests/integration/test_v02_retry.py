import os
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.database import AgentDefinition, Message, ModelConfig, Run, Session
from app.persistence.repositories.catalog import CatalogRepository
from app.persistence.repositories.runs import RunRepository


async def test_retry_creates_new_run_and_preserves_failed_run():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(name=f"retry-model-{suffix}", provider="openai", model_name="fake")
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"retry-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="retry-user")
            db.add(session)
            await db.flush()
            message = Message(
                session_id=session.id, user_id="retry-user", role="user", content="retry me"
            )
            db.add(message)
            await db.flush()
            failed = Run(session_id=session.id, message_id=message.id, status="FAILED")
            db.add(failed)
            await db.commit()
            failed_id = failed.id

        async with factory() as db:
            retried = await RunRepository(db).retry(failed_id)
            assert retried.id != failed_id
            assert retried.parent_run_id == failed_id
            assert retried.message_id == message.id
            assert retried.status == "PENDING"
            assert retried.attempt == 2
            assert (await db.get(Run, failed_id)).status == "FAILED"
    finally:
        await engine.dispose()


async def test_agent_update_records_revision_history():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"revision-model-{suffix}", provider="openai", model_name="fake"
            )
            db.add(model)
            await db.commit()
            catalog = CatalogRepository(db)
            agent = await catalog.save_agent(
                {
                    "name": f"revision-agent-{suffix}",
                    "model_id": model.id,
                    "system_prompt": "first",
                },
                [],
            )
            assert agent.revision == 1
            agent = await catalog.save_agent({"system_prompt": "second"}, [], agent)
            assert agent.revision == 2
            revisions = await catalog.agent_revisions(agent.id)
            assert [row.revision for row in revisions] == [2, 1]
            assert [row.snapshot["system_prompt"] for row in revisions] == ["second", "first"]
    finally:
        await engine.dispose()
