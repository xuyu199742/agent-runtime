import asyncio
import os
from uuid import uuid4

import httpx
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.database import get_db
from app.main import app


@pytest.mark.asyncio
async def test_catalog_session_and_message_idempotence():
    url = os.environ["TEST_DATABASE_URL"]
    engine = create_async_engine(url)
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    suffix = uuid4().hex[:8]
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            model = await client.post(
                "/api/models",
                json={"name": f"model-{suffix}", "provider": "openai", "model_name": "test-model"},
            )
            assert model.status_code == 201, model.text
            agent = await client.post(
                "/api/agents", json={"name": f"agent-{suffix}", "model_id": model.json()["id"]}
            )
            assert agent.status_code == 201, agent.text
            session = await client.post("/api/sessions", json={"agent_id": agent.json()["id"]})
            assert session.status_code == 201, session.text
            body = {"client_message_id": f"message-{suffix}", "content": "你好"}
            first = await client.post(f"/api/sessions/{session.json()['id']}/messages", json=body)
            second = await client.post(f"/api/sessions/{session.json()['id']}/messages", json=body)
            assert first.status_code == 202, first.text
            assert second.json() == first.json()
            run = await client.get(f"/api/runs/{first.json()['run_id']}")
            assert run.json()["status"] == "PENDING"
            conflict = await client.post(
                f"/api/sessions/{session.json()['id']}/messages",
                json={**body, "content": "不同内容"},
            )
            assert conflict.status_code == 409

            concurrent_body = {"client_message_id": f"parallel-{suffix}", "content": "只运行一次"}
            requests = await asyncio.gather(
                *[
                    client.post(
                        f"/api/sessions/{session.json()['id']}/messages", json=concurrent_body
                    )
                    for _ in range(5)
                ]
            )
            assert {response.status_code for response in requests} == {202}
            assert len({response.json()["run_id"] for response in requests}) == 1
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
