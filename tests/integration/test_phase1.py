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
            secret = await client.post(
                "/api/models",
                json={
                    "name": f"secret-{suffix}",
                    "provider": "openai",
                    "model_name": "fake",
                    "config": {"api_key": "should-not-store"},
                },
            )
            assert secret.status_code == 422
            assert "should-not-store" not in secret.text

            spare_model = await client.post(
                "/api/models",
                json={"name": f"spare-{suffix}", "provider": "openai", "model_name": "first"},
            )
            updated_model = await client.put(
                f"/api/models/{spare_model.json()['id']}",
                json={"name": f"spare-{suffix}", "provider": "openai", "model_name": "second"},
            )
            assert updated_model.json()["model_name"] == "second"
            assert (
                await client.delete(f"/api/models/{spare_model.json()['id']}")
            ).status_code == 204
            assert (await client.get(f"/api/models/{spare_model.json()['id']}")).status_code == 404

            spare_tool = await client.post("/api/tools", json={"name": "echo", "type": "NATIVE"})
            if spare_tool.status_code == 201:
                changed_tool = await client.put(
                    f"/api/tools/{spare_tool.json()['id']}",
                    json={"name": "echo", "type": "NATIVE", "description": "回显"},
                )
                assert changed_tool.json()["description"] == "回显"
                assert (
                    await client.delete(f"/api/tools/{spare_tool.json()['id']}")
                ).status_code == 204
            agent = await client.post(
                "/api/agents", json={"name": f"agent-{suffix}", "model_id": model.json()["id"]}
            )
            assert agent.status_code == 201, agent.text
            spare_agent = await client.post(
                "/api/agents",
                json={"name": f"spare-agent-{suffix}", "model_id": model.json()["id"]},
            )
            assert (
                await client.delete(f"/api/agents/{spare_agent.json()['id']}")
            ).status_code == 204
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
            parallel_session = await client.post(
                "/api/sessions", json={"agent_id": agent.json()["id"]}
            )
            requests = await asyncio.gather(
                *[
                    client.post(
                        f"/api/sessions/{parallel_session.json()['id']}/messages",
                        json=concurrent_body,
                    )
                    for _ in range(5)
                ]
            )
            assert {response.status_code for response in requests} == {202}
            assert len({response.json()["run_id"] for response in requests}) == 1

            separate_session = await client.post(
                "/api/sessions", json={"agent_id": agent.json()["id"]}
            )
            distinct = await asyncio.gather(
                *[
                    client.post(
                        f"/api/sessions/{separate_session.json()['id']}/messages",
                        json={
                            "client_message_id": f"distinct-{suffix}-{index}",
                            "content": "并发消息",
                        },
                    )
                    for index in range(2)
                ]
            )
            assert sorted(response.status_code for response in distinct) == [202, 409]
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
