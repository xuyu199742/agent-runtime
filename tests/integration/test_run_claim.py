import os
from uuid import uuid4

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.runs import claim_run, finish_run
from app.infrastructure.database import AgentDefinition, Message, ModelConfig, Run, Session


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
