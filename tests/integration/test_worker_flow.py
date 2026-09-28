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


class FakeToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def test_message_queue_worker_tool_answer_and_sse(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(worker, "session_factory", factory)
    monkeypatch.setattr(
        worker,
        "build_model",
        lambda _config: FakeToolModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "calculator", "args": {"expression": "2+2"}, "id": "call-e2e"}
                    ],
                ),
                AIMessage(content="答案是 4"),
            ]
        ),
    )
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    suffix = uuid4().hex[:8]
    queue = RunQueue(redis, stream=f"test:worker:{suffix}", group=f"test-workers-{suffix}")
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            model = (
                await client.post(
                    "/api/models",
                    json={
                        "name": f"worker-model-{suffix}",
                        "provider": "openai",
                        "model_name": "fake",
                    },
                )
            ).json()
            existing_tools = (await client.get("/api/tools")).json()
            tool = next((item for item in existing_tools if item["name"] == "calculator"), None)
            if tool is None:
                tool = (
                    await client.post("/api/tools", json={"name": "calculator", "type": "NATIVE"})
                ).json()
            agent = (
                await client.post(
                    "/api/agents",
                    json={
                        "name": f"worker-agent-{suffix}",
                        "model_id": model["id"],
                        "tool_ids": [tool["id"]],
                    },
                )
            ).json()
            session = (await client.post("/api/sessions", json={"agent_id": agent["id"]})).json()
            accepted = (
                await client.post(
                    f"/api/sessions/{session['id']}/messages",
                    json={"client_message_id": f"worker-message-{suffix}", "content": "2+2"},
                )
            ).json()
            run_id = accepted["run_id"]

            await queue.ensure_group()
            await redis.delete(f"run:{run_id}:enqueued")
            await queue.enqueue(run_id)
            entries = await queue.read("test-worker", block_ms=100)
            async with AsyncPostgresSaver.from_conn_string(
                os.environ["TEST_CHECKPOINT_DATABASE_URL"]
            ) as saver:
                await saver.setup()
                await worker.process_entry(
                    entries[0][0],
                    entries[0][1],
                    "test-worker",
                    redis,
                    queue,
                    EventStore(redis),
                    saver,
                )

            run = await client.get(f"/api/runs/{run_id}")
            assert run.json()["status"] == "COMPLETED", run.text
            assert run.json()["answer_message_id"]
            events = await client.get(f"/api/runs/{run_id}/events")
            assert "event: tool.completed" in events.text
            assert "event: run.completed" in events.text
            assert "答案是 4" in events.text
            await redis.delete(EventStore.key(run_id), EventStore.sequence_key(run_id))
            durable_run = await client.get(f"/api/runs/{run_id}")
            assert durable_run.json()["answer"] == "答案是 4"

            monkeypatch.setattr(
                worker, "build_model", lambda _config: (_ for _ in ()).throw(ValueError("缺少凭证"))
            )
            failed_session = (
                await client.post("/api/sessions", json={"agent_id": agent["id"]})
            ).json()
            failed_accepted = (
                await client.post(
                    f"/api/sessions/{failed_session['id']}/messages",
                    json={"client_message_id": f"failed-{suffix}", "content": "测试失败"},
                )
            ).json()
            failed_run_id = failed_accepted["run_id"]
            await redis.delete(f"run:{failed_run_id}:enqueued")
            await queue.enqueue(failed_run_id)
            failed_entry = await queue.read("test-worker", block_ms=100)
            async with AsyncPostgresSaver.from_conn_string(
                os.environ["TEST_CHECKPOINT_DATABASE_URL"]
            ) as saver:
                await worker.process_entry(
                    failed_entry[0][0],
                    failed_entry[0][1],
                    "test-worker",
                    redis,
                    queue,
                    EventStore(redis),
                    saver,
                )
            failed_run = await client.get(f"/api/runs/{failed_run_id}")
            assert failed_run.json()["status"] == "FAILED"
            assert failed_run.json()["error_code"] == "MODEL_ERROR"
    finally:
        app.dependency_overrides.clear()
        await redis.delete(queue.stream)
        await redis.aclose()
        await engine.dispose()
