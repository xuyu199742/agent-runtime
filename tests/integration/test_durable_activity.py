"""真实数据库下验证活动正文、恢复与 lease 隔离，不调用外部模型。"""

import asyncio
import os

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.context.errors import ContextLeaseLost
from app.execution.message_content import model_content
from app.persistence.database import RunActivitySnapshot, RunTraceEvent
from app.persistence.repositories.activity import (
    TEXT_LIMIT,
    activity_items,
    append_snapshot,
    bounded,
    preview,
)
from app.persistence.repositories.tool_executions import ToolExecutionStore
from app.runtime.agent import LangChainAgentRuntime
from app.skills.content import freeze_skill
from app.worker.model_recording import ModelCallJournal
from tests.integration.test_execution_timeline import _running_run


class StreamingModel(FakeMessagesListChatModel):
    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        for content, reasoning in [("", "实际思考"), ("正文", ""), ("尾部", "")]:
            yield ChatGenerationChunk(
                message=AIMessageChunk(
                    content=content, additional_kwargs={"reasoning_content": reasoning}
                )
            )
            await asyncio.sleep(0.22)


async def test_streamed_model_activity_is_durable_and_retry_resets():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        journal = ModelCallJournal(factory, run_id, "worker-a", "fake", "fake")
        runtime = LangChainAgentRuntime(
            StreamingModel(responses=[]), [], "", 5, model_call_journal=journal
        )

        async def emit(_kind, _data):
            pass

        async def cancelled():
            return False

        answer = await runtime.run(run_id, [HumanMessage(content="hi")], emit, cancelled)
        assert answer == "正文尾部"
        async with factory() as db:
            items = await activity_items(db, run_id)
            assert len(items) == 1
            content = items[0]["content"]
            assert content == {
                "stepId": items[0]["id"],
                "status": "COMPLETED",
                "text": "正文尾部",
                "reasoning": "实际思考",
            }
            rows = list(
                await db.scalars(
                    select(RunActivitySnapshot)
                    .where(RunActivitySnapshot.run_id == run_id)
                    .order_by(RunActivitySnapshot.sequence)
                )
            )
            assert any(
                row.content["status"] == "RUNNING" and row.content["reasoning"] for row in rows
            )
            assert all(
                not row.data
                for row in await db.scalars(
                    select(RunTraceEvent).where(
                        RunTraceEvent.run_id == run_id,
                        RunTraceEvent.event_type == "activity.updated",
                    )
                )
            )
        step = items[0]["id"]
        execution = await journal.start(step, "AGENT", [HumanMessage(content="hi")])
        async with factory() as db:
            assert (await activity_items(db, run_id))[0]["content"]["text"] == ""
        await journal.stream(step, AIMessageChunk(content="新正文"))
        await journal.fail(execution)
        async with factory() as db:
            content = (await activity_items(db, run_id))[0]["content"]
            assert content["text"] == "新正文" and content["status"] == "FAILED"
            with pytest.raises(ContextLeaseLost):
                await append_snapshot(db, run_id, "worker-other", "bad", "model", {})
    finally:
        await engine.dispose()


async def test_tool_skill_preview_and_completed_replay_are_durable():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        store = ToolExecutionStore(factory, "worker-a")
        skill = {**freeze_skill("example", "真实Skill", {}), "revision": 7}
        kwargs = {"arguments": {"name": "example", "password": "hidden"}, "skill_config": [skill]}
        await store.start(run_id, "call", "skill.read", "READ_ONLY", "hash", **kwargs)
        await store.finish(run_id, "call", "COMPLETED", "真实Skill", None)
        async with factory() as db:
            items = {item["type"]: item["content"] for item in await activity_items(db, run_id)}
            assert items["tool"]["input"]["password"] == "[已脱敏]"
            assert items["tool"]["output"] == "真实Skill"
            assert items["skill"]["status"] == "LOADED"
            assert items["skill"]["revision"] == 7
            assert items["skill"]["contentHash"] == skill["content_hash"]
            before = await db.scalar(
                select(func.count())
                .select_from(RunActivitySnapshot)
                .where(RunActivitySnapshot.run_id == run_id)
            )
        await store.start(run_id, "call", "skill.read", "READ_ONLY", "hash", **kwargs)
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(RunActivitySnapshot)
                    .where(RunActivitySnapshot.run_id == run_id)
                )
                == before
            )
    finally:
        await engine.dispose()


def test_standard_reasoning_summary_and_preview_bounds():
    message = AIMessage(
        content=[
            {"type": "reasoning", "summary": [{"type": "summary_text", "text": "供应商摘要"}]},
            {"type": "text", "text": "正文"},
        ]
    )
    assert model_content(message) == ("正文", "供应商摘要")
    assert len(bounded("你" * TEXT_LIMIT).encode()) <= TEXT_LIMIT
    assert bounded("你" * TEXT_LIMIT).endswith("[内容已截断]")
    assert "secret-value" not in str(preview({"headers": {"Authorization": "secret-value"}}))


async def test_stream_completion_interleaving_and_saturated_dedup(monkeypatch):
    import app.worker.model_recording as recording

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        journal = ModelCallJournal(factory, run_id, "worker-a", "fake", "fake")
        step = f"{run_id}:model:1"
        execution = await journal.start(step, "AGENT", [HumanMessage(content="hi")])
        entered, release = asyncio.Event(), asyncio.Event()
        original = recording.append_snapshot

        async def delayed(*args, **kwargs):
            if args[-1].get("status") == "RUNNING":
                entered.set()
                await release.wait()
            return await original(*args, **kwargs)

        monkeypatch.setattr(recording, "append_snapshot", delayed)
        stream = asyncio.create_task(journal.stream(step, AIMessageChunk(content="partial")))
        await asyncio.wait_for(entered.wait(), 2)
        complete = asyncio.create_task(journal.complete(execution, AIMessage(content="complete")))
        await asyncio.sleep(0)
        assert not complete.done()
        release.set()
        await asyncio.gather(stream, complete)
        async with factory() as db:
            assert (await activity_items(db, run_id))[0]["content"]["status"] == "COMPLETED"
        monkeypatch.setattr(recording, "append_snapshot", original)
        execution = await journal.start(step, "AGENT", [HumanMessage(content="hi")])
        journal.last_write[step] = 0
        await journal.stream(step, AIMessageChunk(content="a" * (TEXT_LIMIT + 1)))
        async with factory() as db:
            before = await db.scalar(
                select(func.count())
                .select_from(RunActivitySnapshot)
                .where(RunActivitySnapshot.run_id == run_id)
            )
        for _ in range(5):
            journal.last_write[step] = 0
            await journal.stream(step, AIMessageChunk(content="more"))
            await journal.stream(step, AIMessageChunk(content=""))
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(RunActivitySnapshot)
                    .where(RunActivitySnapshot.run_id == run_id)
                )
                == before
            )
        await journal.fail(execution, "MODEL_CANCELLED")
        async with factory() as db:
            assert (await activity_items(db, run_id))[0]["content"]["status"] == "CANCELLED"
    finally:
        await engine.dispose()


async def test_client_activity_permissions_history_and_agui_resume(monkeypatch):
    import json
    from uuid import uuid4

    import httpx

    import app.transport.http.v1.client.agui as agui_endpoint
    from app.infrastructure.passwords import hash_password
    from app.main import app
    from app.persistence.database import Run, Session, User, get_db
    from app.persistence.repositories.runs import finish_run

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(agui_endpoint, "session_factory", factory)
    suffix = uuid4().hex[:8]
    try:
        run_id = await _running_run(factory)
        async with factory() as db:
            owner = User(
                username=f"activity-owner-{suffix}",
                display_name="Owner",
                password_hash=hash_password("secret-activity-123"),
            )
            other = User(
                username=f"activity-other-{suffix}",
                display_name="Other",
                password_hash=hash_password("secret-activity-123"),
            )
            db.add_all([owner, other])
            await db.flush()
            run = await db.get(Run, run_id)
            conversation_id = run.session_id
            conversation = await db.get(Session, conversation_id)
            conversation.user_id = owner.id
            await db.commit()
        journal = ModelCallJournal(factory, run_id, "worker-a", "fake", "fake")
        step = f"{run_id}:model:1"
        execution = await journal.start(step, "AGENT", [HumanMessage(content="hi")])
        await journal.complete(
            execution,
            AIMessage(content="答案", additional_kwargs={"reasoning_content": "实际思考"}),
        )
        async with factory() as db:
            assert await finish_run(db, run_id, "worker-a", "答案")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def headers(username):
                login = await client.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": "secret-activity-123"},
                )
                assert login.status_code == 200
                return {"Authorization": f"Bearer {login.json()['access_token']}"}

            owner_headers = await headers(f"activity-owner-{suffix}")
            other_headers = await headers(f"activity-other-{suffix}")
            path = f"/api/v1/client/runs/{run_id}"
            assert (await client.get(f"{path}/activity", headers=other_headers)).status_code == 404
            assert (
                await client.get(f"{path}/ag-ui/events", headers=other_headers)
            ).status_code == 404
            activity = await client.get(f"{path}/activity", headers=owner_headers)
            assert activity.status_code == 200
            assert activity.json()["items"][0]["content"]["reasoning"] == "实际思考"
            messages = await client.get(
                f"/api/v1/client/conversations/{conversation_id}/messages", headers=owner_headers
            )
            assert messages.status_code == 200
            assert all(item["run_id"] == run_id for item in messages.json())
            stream = await client.get(f"{path}/ag-ui/events", headers=owner_headers)
            blocks = stream.text.strip().split("\n\n")
            snapshots = [
                (
                    next(line[4:] for line in block.splitlines() if line.startswith("id: ")),
                    json.loads(
                        next(line[6:] for line in block.splitlines() if line.startswith("data: "))
                    ),
                )
                for block in blocks
                if "event: ACTIVITY_SNAPSHOT" in block
            ]
            assert snapshots[-1][1]["content"] == activity.json()["items"][0]["content"]
            assert snapshots[-1][1]["messageId"] == step
            resumed = await client.get(
                f"{path}/ag-ui/events", headers={**owner_headers, "Last-Event-ID": snapshots[-1][0]}
            )
            assert "ACTIVITY_SNAPSHOT" not in resumed.text
            assert resumed.text.count("TEXT_MESSAGE_CONTENT") == 2  # event 行和 type 字段
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()


@pytest.mark.parametrize("with_new_snapshot", [False, True])
async def test_legacy_tool_rest_and_agui_fallback_preserves_new_snapshots(
    monkeypatch, with_new_snapshot
):
    import json
    from types import SimpleNamespace

    import httpx

    import app.transport.http.v1.client.agui as agui_endpoint
    from app.main import app
    from app.persistence.database import Run, Session, ToolExecution, get_db
    from app.persistence.repositories.runs import finish_run
    from app.persistence.repositories.traces import ExecutionRecorder
    from app.transport.http.v1.dependencies import authenticated

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    monkeypatch.setattr(agui_endpoint, "session_factory", factory)
    try:
        run_id = await _running_run(factory)
        async with factory() as db:
            run = await db.get(Run, run_id)
            session = await db.get(Session, run.session_id)
            app.dependency_overrides[authenticated] = lambda: SimpleNamespace(id=session.user_id)
            tool = ToolExecution(
                run_id=run_id,
                tool_call_id="old",
                tool_name="skill.read",
                effect_type="READ_ONLY",
                idempotency_key=f"{run_id}:old",
                args_hash="old-hash",
                status="COMPLETED",
                result_content='{"result":"历史结果","token":"private-secret"}',
            )
            db.add(tool)
            await db.flush()
            recorder = ExecutionRecorder(db)
            for kind in ("tool.started", "tool.completed"):
                await recorder.append(
                    run_id,
                    kind,
                    {"name": "skill.read", "tool_call_id": "old"},
                    worker_id="worker-a",
                    ref_type="tool_execution",
                    ref_id=tool.id,
                )
            # 同 Run 的另一新调用不能导致旧调用活动被抑制。
            await append_snapshot(
                db,
                run_id,
                "worker-a",
                "tool:other",
                "tool",
                {"name": "echo", "toolCallId": "other", "status": "COMPLETED", "output": "新调用"},
            )
            expected = {
                "name": "skill.read",
                "toolCallId": "old",
                "status": "COMPLETED",
                "input": None,
                "output": {"result": "历史结果", "token": "[已脱敏]"},
                "error": None,
            }
            if with_new_snapshot:
                expected = {**expected, "input": {"name": "真实输入"}, "output": "新快照优先"}
                await append_snapshot(db, run_id, "worker-a", "tool:old", "tool", expected)
            await db.commit()
        async with factory() as db:
            assert await finish_run(db, run_id, "worker-a", "答案")
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:
            path = f"/api/v1/client/runs/{run_id}"
            rest = await client.get(f"{path}/activity")
            assert rest.status_code == 200
            items = rest.json()["items"]
            assert {item["type"] for item in items} == {"tool"}
            assert len([item for item in items if item["id"] == "tool:old"]) == 1
            assert next(item["content"] for item in items if item["id"] == "tool:old") == expected
            stream = await client.get(f"{path}/ag-ui/events")

            def snapshots(text):
                result = []
                for block in text.strip().split("\n\n"):
                    if "event: ACTIVITY_SNAPSHOT" not in block:
                        continue
                    event = json.loads(
                        next(line[6:] for line in block.splitlines() if line.startswith("data: "))
                    )
                    if event["messageId"] == "tool:old":
                        cursor = next(
                            line[4:] for line in block.splitlines() if line.startswith("id: ")
                        )
                        result.append((cursor, event))
                return result

            old = snapshots(stream.text)
            assert len(old) == (1 if with_new_snapshot else 2)
            assert all(event["content"] == expected for _, event in old)
            assert "private-secret" not in stream.text
            resumed = await client.get(
                f"{path}/ag-ui/events", headers={"Last-Event-ID": old[-1][0]}
            )
            assert snapshots(resumed.text) == []
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
