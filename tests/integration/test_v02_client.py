import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.infrastructure.passwords import hash_password
from app.main import app
from app.persistence.database import (
    AgentDefinition,
    Approval,
    ExecutionSpec,
    ModelConfig,
    Run,
    User,
    get_db,
)
from app.persistence.repositories.traces import trace_event


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
                name=f"client-model-{suffix}",
                provider="openai",
                model_name="private-model",
                config={"context_window": 32768, "max_output_tokens": 4096},
            )
            db.add(model)
            await db.flush()
            agent = AgentDefinition(
                name=f"client-agent-{suffix}",
                model_id=model.id,
                system_prompt="private-prompt",
                max_tool_calls=2,
                max_external_writes=1,
                max_duration_seconds=120,
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
                assert spec.schema_version == 5
                instruction = next(
                    section["content"]
                    for section in spec.snapshot["prompt"]["sections"]
                    if section["name"] == "agent_instruction"
                )
                assert instruction == "private-prompt"
                assert spec.snapshot["prompt"]["sections"][0]["content"]
                assert spec.snapshot["model"]["model_name"] == "private-model"
                assert spec.snapshot["execution_budget"] == {
                    "max_model_calls": 10,
                    "max_tool_calls": 2,
                    "max_external_writes": 1,
                    "max_duration_seconds": 120,
                }
                agent_db = await db.get(AgentDefinition, agent.id)
                agent_db.system_prompt = "changed-after-submit"
                agent_db.max_tool_calls = 100
                agent_db.max_external_writes = 100
                agent_db.max_duration_seconds = 3600
                await db.commit()
            async with factory() as db:
                persisted = await db.get(Run, run_id)
                preserved = await db.get(ExecutionSpec, persisted.execution_spec_id)
                assert preserved.snapshot["execution_budget"]["max_tool_calls"] == 2
                assert preserved.snapshot["execution_budget"]["max_external_writes"] == 1
                assert preserved.snapshot["execution_budget"]["max_duration_seconds"] == 120
                preserved_instruction = next(
                    section["content"]
                    for section in preserved.snapshot["prompt"]["sections"]
                    if section["name"] == "agent_instruction"
                )
                assert preserved_instruction == "private-prompt"
                persisted.status = "RUNNING"
                persisted.lease_owner = "worker-test"
                persisted.lease_until = datetime.now(UTC) + timedelta(minutes=5)
                await db.commit()
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
                        tool_budget=_kwargs["tool_execution_store"].budget,
                        effect_budget=_kwargs["effect_store"].budget,
                    )

                async def run(self, *_args, **_kwargs):
                    return "ok"

            async def no_publish(*_args, **_kwargs):
                return None

            monkeypatch.setattr(runner, "session_factory", factory)
            monkeypatch.setattr(runner, "LangChainAgentRuntime", CapturingRuntime)
            monkeypatch.setattr(runner, "build_model", lambda config: config.definition)
            monkeypatch.setattr(runner, "build_tools", lambda tools: tools)
            monkeypatch.setattr(runner, "safe_publish", no_publish)
            assert await runner.run_agent(run_id, False, None, None, None, "worker-test") == "ok"
            assert "private-prompt" in captured["system_prompt"]
            assert captured["model"].model_name == "private-model"
            assert captured["tool_budget"].max_tool_calls == 2
            assert captured["effect_budget"].max_external_writes == 1
            assert (
                await client.get(f"/api/v1/client/runs/{run_id}", headers=bob)
            ).status_code == 404
            assert (
                await client.get(f"/api/v1/client/runs/{run_id}", headers=alice)
            ).status_code == 200
            from app.persistence.repositories.runs import finish_run
            from app.transport.http.v1.client import agui

            monkeypatch.setattr(agui, "session_factory", factory)
            async with factory() as db:
                assert await finish_run(db, run_id, "worker-test", "ok")
                final_run = await db.get(Run, run_id)
                final_sequence = final_run.trace_sequence
            assert (
                await client.get(f"/api/v1/client/runs/{run_id}/ag-ui/events", headers=bob)
            ).status_code == 404
            agui_events = await client.get(
                f"/api/v1/client/runs/{run_id}/ag-ui/events", headers=alice
            )
            assert agui_events.status_code == 200, agui_events.text
            assert "event: RUN_STARTED" in agui_events.text
            assert "event: TEXT_MESSAGE_CONTENT" in agui_events.text
            assert "event: RUN_FINISHED" in agui_events.text
            replay = await client.get(
                f"/api/v1/client/runs/{run_id}/ag-ui/events",
                headers={**alice, "Last-Event-ID": f"{final_sequence}:t:1"},
            )
            assert "event: TEXT_MESSAGE_CONTENT" not in replay.text
            assert "event: TEXT_MESSAGE_END" in replay.text
            assert "event: RUN_FINISHED" in replay.text
            async with factory() as db:
                paused = await db.get(Run, run_id)
                paused.status = "WAITING"
                approval = Approval(
                    run_id=run_id,
                    tool_call_id="call-test",
                    tool_name="write",
                    title="确认写入",
                    description="测试审批续传",
                    risk="high",
                )
                db.add(approval)
                await db.flush()
                approval_id = approval.id
                await db.commit()
            waiting = await client.get(f"/api/v1/client/runs/{run_id}/ag-ui/events", headers=alice)
            waiting_cursor = f"{final_sequence}:t:0"
            assert f"id: {waiting_cursor}\n" in waiting.text
            async with factory() as db:
                resumed = await db.get(Run, run_id)
                resumed.status = "COMPLETED"
                approved = await db.get(Approval, approval_id)
                approved.status = "APPROVED"
                resumed.trace_sequence += 1
                db.add(
                    trace_event(
                        run_id,
                        resumed.trace_sequence,
                        "approval.approved",
                        {"approval_id": approval_id, "tool_call_id": "call-test"},
                    )
                )
                await db.commit()
            resumed_events = await client.get(
                f"/api/v1/client/runs/{run_id}/ag-ui/events",
                headers={**alice, "Last-Event-ID": waiting_cursor},
            )
            assert f"id: {final_sequence + 1}:0\n" in resumed_events.text
            assert '"status": "APPROVED"' in resumed_events.text
            legacy_replay = await client.get(
                f"/api/v1/client/runs/{run_id}/ag-ui/events",
                headers={**alice, "Last-Event-ID": f"{final_sequence + 1}:0"},
            )
            assert '"status": "APPROVED"' in legacy_replay.text
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
