import os
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.passwords import hash_password
from app.main import app
from app.persistence.database import AgentDefinition, ExecutionSpec, ModelConfig, Run, User, get_db


async def test_client_routes_hide_config_and_isolate_conversations(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"client-model-{suffix}", provider="openai", model_name="private-model"
            )
            db.add(model)
            await db.flush()
            agent = AgentDefinition(
                name=f"client-agent-{suffix}", model_id=model.id, system_prompt="private-prompt"
            )
            db.add(agent)
            db.add_all(
                [
                    User(
                        username=f"alice-{suffix}",
                        display_name="Alice",
                        password_hash=hash_password("alice-secret-123"),
                    ),
                    User(
                        username=f"bob-{suffix}",
                        display_name="Bob",
                        password_hash=hash_password("bob-secret-1234"),
                    ),
                ]
            )
            await db.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def headers(username, password):
                response = await client.post(
                    "/api/v1/auth/login", json={"username": username, "password": password}
                )
                assert response.status_code == 200, response.text
                return {"Authorization": f"Bearer {response.json()['access_token']}"}

            alice = await headers(f"alice-{suffix}", "alice-secret-123")
            bob = await headers(f"bob-{suffix}", "bob-secret-1234")
            agent_response = await client.get(f"/api/v1/client/agents/{agent.id}", headers=alice)
            assert agent_response.status_code == 200
            assert not {"system_prompt", "model_id", "tool_ids"} & agent_response.json().keys()
            created = await client.post(
                "/api/v1/client/conversations", headers=alice, json={"agent_id": agent.id}
            )
            assert created.status_code == 201, created.text
            conversation_id = created.json()["id"]
            assert (await client.get("/api/v1/client/conversations", headers=alice)).json()[
                "total"
            ] == 1
            assert (await client.get("/api/v1/client/conversations", headers=bob)).json()[
                "total"
            ] == 0
            assert (
                await client.get(f"/api/v1/client/conversations/{conversation_id}", headers=bob)
            ).status_code == 404
            sent = await client.post(
                f"/api/v1/client/conversations/{conversation_id}/messages",
                headers=alice,
                json={"client_message_id": f"message-{suffix}", "content": "你好"},
            )
            assert sent.status_code == 202, sent.text
            assert (
                await client.get(
                    f"/api/v1/client/conversations/{conversation_id}/messages", headers=bob
                )
            ).status_code == 404
            run_id = sent.json()["run"]["id"]
            async with factory() as db:
                run = await db.get(Run, run_id)
                spec = await db.get(ExecutionSpec, run.execution_spec_id)
                assert spec.agent_revision == 1
                assert spec.snapshot["system_prompt"] == "private-prompt"
                assert spec.snapshot["model"]["model_name"] == "private-model"
                agent_db = await db.get(AgentDefinition, agent.id)
                agent_db.system_prompt = "changed-after-submit"
                await db.commit()
            async with factory() as db:
                preserved = await db.get(ExecutionSpec, run.execution_spec_id)
                assert preserved.snapshot["system_prompt"] == "private-prompt"
            from app.worker import runner

            captured = {}

            class CapturingRuntime:
                def __init__(
                    self, model, tools, system_prompt, max_model_calls, checkpointer, **_kwargs
                ):
                    captured.update(
                        model=model,
                        tools=tools,
                        system_prompt=system_prompt,
                        max_model_calls=max_model_calls,
                    )

                async def run(self, *_args, **_kwargs):
                    return "ok"

            async def no_publish(*_args):
                return None

            monkeypatch.setattr(runner, "session_factory", factory)
            monkeypatch.setattr(runner, "LangChainAgentRuntime", CapturingRuntime)
            monkeypatch.setattr(runner, "build_model", lambda config: config.definition)
            monkeypatch.setattr(runner, "build_tools", lambda tools: tools)
            monkeypatch.setattr(runner, "safe_publish", no_publish)
            assert await runner.run_agent(run_id, False, None, None, None) == "ok"
            assert captured["system_prompt"] == "private-prompt"
            assert captured["model"].model_name == "private-model"
            assert (
                await client.get(f"/api/v1/client/runs/{run_id}", headers=bob)
            ).status_code == 404
            assert (
                await client.get(f"/api/v1/client/runs/{run_id}", headers=alice)
            ).status_code == 200
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
