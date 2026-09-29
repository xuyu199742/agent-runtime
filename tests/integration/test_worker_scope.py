import asyncio
import os
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.persistence.database import AgentDefinition, Message, ModelConfig, Run, Session
from app.worker import runner as worker


@pytest.mark.parametrize(
    "stop_reason", ["heartbeat_error", "lease_lost", "redis_error", "shutdown"]
)
async def test_scope_stops_agent_without_committing_terminal_state(monkeypatch, stop_reason):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    stopped = asyncio.Event()
    try:
        async with factory() as db:
            model = ModelConfig(name=f"scope-model-{suffix}", provider="openai", model_name="fake")
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"scope-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="user")
            db.add(session)
            await db.flush()
            message = Message(session_id=session.id, user_id="user", role="user", content="hi")
            db.add(message)
            await db.flush()
            run = Run(
                session_id=session.id, message_id=message.id, status="RUNNING", lease_owner="a"
            )
            db.add(run)
            await db.commit()
            run_id = run.id

        async def long_agent(*_args):
            try:
                await asyncio.sleep(60)
            finally:
                stopped.set()

        async def broken_heartbeat(*_args):
            if stop_reason == "heartbeat_error":
                raise ConnectionError("postgres lost")
            return stop_reason in {"shutdown", "redis_error"}

        class RedisStub:
            async def exists(self, _key):
                if stop_reason == "redis_error":
                    from redis.exceptions import ConnectionError as RedisConnectionError

                    raise RedisConnectionError("redis lost")
                return False

        monkeypatch.setattr(worker, "session_factory", factory)
        monkeypatch.setattr(worker, "run_agent", long_agent)
        monkeypatch.setattr(worker, "extend_lease", broken_heartbeat)

        execution = asyncio.create_task(
            worker.execute_run(run_id, "a", False, RedisStub(), None, None, heartbeat_interval=0.01)
        )
        if stop_reason == "shutdown":
            await asyncio.sleep(0.03)
            execution.cancel()
            with pytest.raises(asyncio.CancelledError):
                await execution
        else:
            assert not await asyncio.wait_for(execution, timeout=1)
        assert stopped.is_set()
        async with factory() as db:
            assert (await db.get(Run, run_id)).status == "RUNNING"
    finally:
        await engine.dispose()
