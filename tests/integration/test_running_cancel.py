import asyncio
import os
from uuid import uuid4

import httpx
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app import worker
from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.events import EventStore
from app.infrastructure.redis_queue import RunQueue
from app.main import app


class SlowModel(FakeMessagesListChatModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        await asyncio.sleep(30)
        return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)


async def test_running_run_cancels_independently_of_sse(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(worker, "session_factory", factory)
    monkeypatch.setattr(
        worker, "build_model", lambda _config: SlowModel(responses=[AIMessage(content="不应完成")])
    )
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    suffix = uuid4().hex[:8]
    queue = RunQueue(redis, stream=f"test:cancel:{suffix}", group=f"test-workers-{suffix}")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            model = (
                await client.post(
                    "/api/models",
                    json={
                        "name": f"cancel-model-{suffix}",
                        "provider": "openai",
                        "model_name": "fake",
                    },
                )
            ).json()
            agent = (
                await client.post(
                    "/api/agents", json={"name": f"cancel-agent-{suffix}", "model_id": model["id"]}
                )
            ).json()
            session = (await client.post("/api/sessions", json={"agent_id": agent["id"]})).json()
            accepted = (
                await client.post(
                    f"/api/sessions/{session['id']}/messages",
                    json={
                        "client_message_id": f"cancel-running-{suffix}",
                        "content": "请长时间思考",
                    },
                )
            ).json()
            run_id = accepted["run_id"]
            await queue.ensure_group()
            await redis.delete(f"run:{run_id}:enqueued")
            await queue.enqueue(run_id)
            entry = (await queue.read("test-worker", block_ms=100))[0]
            async with AsyncPostgresSaver.from_conn_string(
                os.environ["TEST_CHECKPOINT_DATABASE_URL"]
            ) as saver:
                await saver.setup()
                processing = asyncio.create_task(
                    worker.process_entry(
                        entry[0], entry[1], "test-worker", redis, queue, EventStore(redis), saver
                    )
                )
                for _ in range(30):
                    if (await client.get(f"/api/runs/{run_id}")).json()["status"] == "RUNNING":
                        break
                    await asyncio.sleep(0.1)
                cancelled = await client.post(f"/api/runs/{run_id}/cancel")
                assert cancelled.status_code == 200
                await asyncio.wait_for(processing, timeout=8)
            run = await client.get(f"/api/runs/{run_id}")
            assert run.json()["status"] == "CANCELLED"
    finally:
        app.dependency_overrides.clear()
        await redis.delete(queue.stream, f"run:{run_id}:cancel")
        await redis.aclose()
        await engine.dispose()
