import json
import os
from uuid import uuid4

import httpx
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.events import EventStore
from app.main import app


async def test_sse_replays_after_disconnect_and_pending_run_can_cancel():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    suffix = uuid4().hex[:8]
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            model = (
                await client.post(
                    "/api/models",
                    json={
                        "name": f"sse-model-{suffix}",
                        "provider": "openai",
                        "model_name": "fake",
                    },
                )
            ).json()
            agent = (
                await client.post(
                    "/api/agents", json={"name": f"sse-agent-{suffix}", "model_id": model["id"]}
                )
            ).json()
            session = (await client.post("/api/sessions", json={"agent_id": agent["id"]})).json()
            accepted = (
                await client.post(
                    f"/api/sessions/{session['id']}/messages",
                    json={"client_message_id": f"sse-{suffix}", "content": "测试"},
                )
            ).json()
            run_id = accepted["run_id"]
            store = EventStore(redis)
            await store.publish(run_id, "run.started", {})
            await store.publish(run_id, "model.delta", {"text": "答案"})
            await store.publish(run_id, "run.completed", {"answer": "答案"})

            response = await client.get(f"/api/runs/{run_id}/events?after=1")
            assert response.status_code == 200, response.text
            assert "id: 2\nevent: model.delta" in response.text
            assert "id: 3\nevent: run.completed" in response.text
            assert "id: 1\n" not in response.text
            data_lines = [
                line.removeprefix("data: ")
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]
            assert json.loads(data_lines[-1])["sequence"] == 3
            await redis.delete(store.key(run_id), store.sequence_key(run_id))
            expired = await client.get(f"/api/runs/{run_id}/events?after=1")
            assert expired.status_code == 410

            next_session = (
                await client.post("/api/sessions", json={"agent_id": agent["id"]})
            ).json()
            pending = (
                await client.post(
                    f"/api/sessions/{next_session['id']}/messages",
                    json={"client_message_id": f"cancel-{suffix}", "content": "取消"},
                )
            ).json()
            cancelled = await client.post(f"/api/runs/{pending['run_id']}/cancel")
            assert cancelled.status_code == 200
            assert cancelled.json()["status"] == "CANCELLED"
    finally:
        app.dependency_overrides.clear()
        await redis.aclose()
        await engine.dispose()
