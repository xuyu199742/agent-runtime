import os
from uuid import uuid4

import httpx
from redis.asyncio import Redis
from redis.exceptions import ConnectionError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.runs import pending_run_ids
from app.config import get_settings
from app.infrastructure.database import get_db
from app.infrastructure.redis_queue import RunQueue
from app.main import app


async def test_redis_enqueue_failure_keeps_pending_run_for_recovery(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    suffix = uuid4().hex[:8]
    original_enqueue = RunQueue.enqueue

    async def offline(_self, _run_id):
        raise ConnectionError("Redis 暂不可用")

    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            model = (
                await client.post(
                    "/api/models",
                    json={
                        "name": f"outage-model-{suffix}",
                        "provider": "openai",
                        "model_name": "fake",
                    },
                )
            ).json()
            agent = (
                await client.post(
                    "/api/agents", json={"name": f"outage-agent-{suffix}", "model_id": model["id"]}
                )
            ).json()
            session = (await client.post("/api/sessions", json={"agent_id": agent["id"]})).json()
            monkeypatch.setattr(RunQueue, "enqueue", offline)
            response = await client.post(
                f"/api/sessions/{session['id']}/messages",
                json={"client_message_id": f"outage-{suffix}", "content": "继续执行"},
            )
            assert response.status_code == 202
            run_id = response.json()["run_id"]
            async with factory() as db:
                assert run_id in await pending_run_ids(db)
            monkeypatch.setattr(RunQueue, "enqueue", original_enqueue)
            redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
            try:
                assert await RunQueue(redis).enqueue(run_id)
            finally:
                await redis.aclose()
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
