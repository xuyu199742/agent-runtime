import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from sqlalchemy import update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.database import AgentDefinition, Message, ModelConfig, Run, Session
from app.persistence.repositories.runs import claim_run, extend_lease, finish_run


async def test_one_worker_claims_and_finishes_run():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"claim-model-{suffix}", provider="openai", model_name="fake", config={}
            )
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"claim-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="local-dev-user")
            db.add(session)
            await db.flush()
            message = Message(
                session_id=session.id, user_id=session.user_id, role="user", content="你好"
            )
            db.add(message)
            await db.flush()
            run = Run(session_id=session.id, message_id=message.id, status="PENDING")
            db.add(run)
            await db.commit()
            run_id = run.id

        async with factory() as db:
            assert await claim_run(db, run_id, "worker-a")
        async with factory() as db:
            assert not await claim_run(db, run_id, "worker-b")
            assert await finish_run(db, run_id, "worker-a", "完成")
            await db.refresh(run := await db.get(Run, run_id))
            assert run.status == "COMPLETED"
            assert (await db.get(Message, run.answer_message_id)).content == "完成"
    finally:
        await engine.dispose()


async def test_expired_owner_cannot_renew_or_commit_after_reclaim():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(name=f"fence-model-{suffix}", provider="openai", model_name="fake")
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"fence-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="user")
            db.add(session)
            await db.flush()
            message = Message(session_id=session.id, user_id="user", role="user", content="hi")
            db.add(message)
            await db.flush()
            run = Run(session_id=session.id, message_id=message.id, status="PENDING")
            db.add(run)
            await db.commit()
            run_id = run.id
        async with factory() as db:
            assert await claim_run(db, run_id, "a")
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(lease_until=datetime.now(UTC) - timedelta(seconds=1))
            )
            await db.commit()
        async with factory() as db:
            assert not await extend_lease(db, run_id, "a")
            assert not await finish_run(db, run_id, "a", "stale")
            assert await claim_run(db, run_id, "b")
            assert not await finish_run(db, run_id, "a", "stale")
            assert await finish_run(db, run_id, "b", "fresh")
        async with factory() as db:
            run = await db.get(Run, run_id)
            assert (await db.get(Message, run.answer_message_id)).content == "fresh"
    finally:
        await engine.dispose()
