import asyncio
import os
from uuid import uuid4

import pytest
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.messaging.events import EventStore
from app.messaging.run_queue import RunQueue
from app.persistence.database import AgentDefinition, Message, ModelConfig, Run, Session
from app.runtime.checkpoint import create_checkpoint_pool, create_saver
from app.worker import runner
from app.worker.consumer import consume_queue


async def test_two_runs_execute_concurrently_and_commit_once(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    suffix = uuid4().hex[:8]
    queue = RunQueue(redis, stream=f"test:parallel:{suffix}", group=f"test-parallel-{suffix}")
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    running = 0
    completed = 0
    run_ids = []
    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"parallel-model-{suffix}", provider="openai", model_name="fake"
            )
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"parallel-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            for _ in range(2):
                session = Session(agent_id=agent.id, user_id="user")
                db.add(session)
                await db.flush()
                message = Message(session_id=session.id, user_id="user", role="user", content="hi")
                db.add(message)
                await db.flush()
                run = Run(session_id=session.id, message_id=message.id, status="PENDING")
                db.add(run)
                await db.flush()
                run_ids.append(run.id)
            await db.commit()

        async def blocked_agent(run_id, *_args):
            nonlocal running
            running += 1
            if running == 2:
                started.set()
            try:
                await release.wait()
                return f"answer:{run_id}"
            finally:
                running -= 1

        monkeypatch.setattr(runner, "session_factory", factory)
        monkeypatch.setattr(runner, "run_agent", blocked_agent)
        await queue.ensure_group()
        for run_id in run_ids:
            await queue.enqueue(run_id)

        pool = create_checkpoint_pool(os.environ["TEST_CHECKPOINT_DATABASE_URL"], concurrency=2)
        async with pool:
            saver = create_saver(pool)
            await saver.setup()

            async def handle(stream_id, fields):
                nonlocal completed
                await runner.process_entry(
                    stream_id,
                    fields,
                    "parallel-worker",
                    redis,
                    queue,
                    EventStore(redis),
                    create_saver(pool),
                )
                completed += 1
                if completed == 2:
                    finished.set()

            consumer = asyncio.create_task(
                consume_queue(queue, "parallel-worker", handle, concurrency=2)
            )
            try:
                await asyncio.wait_for(started.wait(), 2)
                release.set()
                await asyncio.wait_for(finished.wait(), 2)
            finally:
                consumer.cancel()
                with pytest.raises(asyncio.CancelledError):
                    await consumer
        async with factory() as db:
            for run_id in run_ids:
                run = await db.get(Run, run_id)
                assert run.status == "COMPLETED"
                assert run.answer_message_id is not None
    finally:
        for run_id in run_ids:
            await redis.delete(f"run:{run_id}:enqueued", EventStore.key(run_id))
        await redis.delete(queue.stream)
        await redis.aclose()
        await engine.dispose()
