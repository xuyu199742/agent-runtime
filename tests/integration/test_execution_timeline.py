import asyncio
import hashlib
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.base import empty_checkpoint
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.context.errors import ContextLeaseLost
from app.infrastructure.passwords import hash_password
from app.main import app
from app.persistence.database import (
    AgentDefinition,
    Approval,
    Message,
    ModelConfig,
    ModelExecution,
    Permission,
    Role,
    Run,
    RunTraceEvent,
    Session,
    ToolExecution,
    User,
    get_db,
)
from app.persistence.repositories import traces
from app.persistence.repositories.approvals import ApprovalRepository
from app.persistence.repositories.runs import end_run, finish_run
from app.persistence.repositories.tool_executions import ToolExecutionStore
from app.runtime.checkpoint import create_checkpoint_pool, create_run_saver, create_saver
from app.runtime.errors import ToolResultUnavailable
from app.runtime.middleware import ToolErrorMiddleware
from app.worker.model_recording import ModelCallJournal
from app.worker.runner import classify_run_error


async def _running_run(factory):
    suffix = uuid4().hex[:8]
    async with factory() as db:
        model = ModelConfig(name=f"timeline-model-{suffix}", provider="openai", model_name="fake")
        db.add(model)
        await db.flush()
        agent = AgentDefinition(name=f"timeline-agent-{suffix}", model_id=model.id)
        db.add(agent)
        await db.flush()
        session = Session(agent_id=agent.id, user_id=f"timeline-user-{suffix}")
        db.add(session)
        await db.flush()
        message = Message(
            session_id=session.id, user_id=session.user_id, role="user", content="hello"
        )
        db.add(message)
        await db.flush()
        run = Run(
            session_id=session.id,
            message_id=message.id,
            status="RUNNING",
            lease_owner="worker-a",
            lease_until=datetime.now(UTC) + timedelta(seconds=45),
        )
        db.add(run)
        await db.commit()
        return run.id


async def test_process_trace_is_fenced_and_terminal_sequence_is_atomic():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        assert hasattr(traces, "ExecutionRecorder")
        async with factory() as db:
            recorder = traces.ExecutionRecorder(db)
            assert (
                await recorder.append(
                    run_id, "model.started", {"step_id": "step-1"}, worker_id="worker-b"
                )
                is None
            )
            assert (
                await recorder.append(
                    run_id, "model.started", {"step_id": "step-1"}, worker_id="worker-a"
                )
                == 1
            )
            await db.commit()
        async with factory() as db:
            assert await finish_run(db, run_id, "worker-a", "完成")
        async with factory() as db:
            run = await db.get(Run, run_id)
            rows = list(
                await db.scalars(
                    select(RunTraceEvent)
                    .where(RunTraceEvent.run_id == run_id)
                    .order_by(RunTraceEvent.sequence)
                )
            )
            assert run.trace_sequence == 2
            assert [(row.sequence, row.event_type) for row in rows] == [
                (1, "model.started"),
                (2, "run.completed"),
            ]
    finally:
        await engine.dispose()


async def test_model_step_retry_records_new_attempt_and_fences_old_owner():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        assert hasattr(traces.ExecutionRecorder, "start_model")
        inputs = [{"role": "user", "content": "hello", "tool_calls": []}]
        async with factory() as db:
            first = await traces.ExecutionRecorder(db).start_model(
                run_id,
                "worker-a",
                step_id=f"{run_id}:model:1",
                phase="AGENT",
                provider="openai",
                model_name="fake",
                input_messages=inputs,
            )
            await db.commit()
        assert first.attempt == 1
        async with factory() as db:
            run = await db.get(Run, run_id, with_for_update=True)
            run.lease_owner = "worker-b"
            run.lease_until = datetime.now(UTC) + timedelta(seconds=45)
            await db.commit()
        async with factory() as db:
            recorder = traces.ExecutionRecorder(db)
            assert not await recorder.complete_model(
                first.id,
                "worker-a",
                {"role": "assistant", "content": "旧结果", "tool_calls": []},
            )
            await db.rollback()
        async with factory() as db:
            second = await traces.ExecutionRecorder(db).start_model(
                run_id,
                "worker-b",
                step_id=f"{run_id}:model:1",
                phase="AGENT",
                provider="openai",
                model_name="fake",
                input_messages=inputs,
            )
            await db.commit()
        assert second.attempt == 2
        async with factory() as db:
            assert await traces.ExecutionRecorder(db).complete_model(
                second.id,
                "worker-b",
                {"role": "assistant", "content": "新结果", "tool_calls": []},
            )
            await db.commit()
        async with factory() as db:
            rows = list(
                await db.scalars(
                    select(ModelExecution)
                    .where(ModelExecution.run_id == run_id)
                    .order_by(ModelExecution.attempt)
                )
            )
            assert [(row.attempt, row.status) for row in rows] == [
                (1, "ABANDONED"),
                (2, "COMPLETED"),
            ]
            assert rows[0].output_message is None
            assert rows[1].output_message["content"] == "新结果"
    finally:
        await engine.dispose()


async def test_model_fact_committed_before_checkpoint_keeps_both_attempts():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        step_id = f"{run_id}:model:1"
        journal = ModelCallJournal(factory, run_id, "worker-a", "openai", "fake")
        first = await journal.start(step_id, "AGENT", [HumanMessage(content="hi")])
        await journal.complete(first, AIMessage(content="first answer"))
        # 故障注入：模型事实已经提交，LangGraph 尚未来得及写检查点。
        pool = create_checkpoint_pool(os.environ["TEST_CHECKPOINT_DATABASE_URL"], 1)
        async with pool:
            saver = create_saver(pool)
            assert await saver.aget_tuple({"configurable": {"thread_id": run_id}}) is None
        second = await journal.start(step_id, "AGENT", [HumanMessage(content="hi")])
        await journal.complete(second, AIMessage(content="second answer"))
        async with factory() as db:
            rows = list(
                await db.scalars(
                    select(ModelExecution)
                    .where(ModelExecution.run_id == run_id)
                    .order_by(ModelExecution.attempt)
                )
            )
            assert [(row.attempt, row.output_message["content"]) for row in rows] == [
                (1, "first answer"),
                (2, "second answer"),
            ]
            events = list(
                await db.scalars(
                    select(RunTraceEvent)
                    .where(RunTraceEvent.run_id == run_id)
                    .order_by(RunTraceEvent.sequence)
                )
            )
            assert [
                (row.event_type, row.attempt)
                for row in events
                if row.event_type != "activity.updated"
            ] == [
                ("model.started", 1),
                ("model.completed", 1),
                ("model.started", 2),
                ("model.completed", 2),
            ]
    finally:
        await engine.dispose()


async def test_late_checkpoint_write_is_possible_without_fence_and_rejected_with_fence():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    pool = create_checkpoint_pool(os.environ["TEST_CHECKPOINT_DATABASE_URL"], 2)
    try:
        run_id = await _running_run(factory)
        config = {"configurable": {"thread_id": run_id, "checkpoint_ns": ""}}
        metadata = {"source": "loop", "step": 0, "parents": {}}
        async with pool:
            plain = create_saver(pool)
            await plain.setup()
            first = empty_checkpoint()
            first["channel_values"] = {"owner": "worker-b"}
            old_worker_ready = asyncio.Event()
            allow_old_worker = asyncio.Event()

            async def late_old_worker_write():
                old_worker_ready.set()
                await allow_old_worker.wait()
                late = empty_checkpoint()
                late["channel_values"] = {"owner": "worker-a"}
                await plain.aput(config, late, metadata, {})
                return late

            old_task = asyncio.create_task(late_old_worker_write())
            await old_worker_ready.wait()
            async with factory() as db:
                run = await db.get(Run, run_id, with_for_update=True)
                run.lease_owner = "worker-b"
                await db.commit()
            await plain.aput(config, first, metadata, {})
            allow_old_worker.set()
            late = await old_task
            assert (await plain.aget_tuple(config)).checkpoint["channel_values"][
                "owner"
            ] == "worker-a"

            fenced = create_run_saver(pool, run_id, "worker-a")
            with pytest.raises(ContextLeaseLost):
                await fenced.aput(config, empty_checkpoint(), metadata, {})
            with pytest.raises(ContextLeaseLost):
                await fenced.aput_writes(
                    {"configurable": {**config["configurable"], "checkpoint_id": late["id"]}},
                    [("channel", "late")],
                    "late-task",
                )
            assert (await plain.aget_tuple(config)).checkpoint["id"] == late["id"]
    finally:
        await engine.dispose()


async def test_completed_tool_with_missing_result_fails_run_without_reexecution():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        store = ToolExecutionStore(factory, "worker-a")
        call = {"name": "echo", "id": "call-1", "args": {"text": "hello"}}
        args_hash = hashlib.sha256(b'{"text": "hello"}').hexdigest()
        await store.start(run_id, call["id"], call["name"], "READ_ONLY", args_hash)
        await store.finish(run_id, call["id"], "COMPLETED", None, None)
        invoked = False

        async def handler(_request):
            nonlocal invoked
            invoked = True
            raise AssertionError("不能重新执行已经完成的 Tool")

        middleware = ToolErrorMiddleware(store=store, run_id=run_id)
        with pytest.raises(ToolResultUnavailable) as error:
            await middleware.awrap_tool_call(SimpleNamespace(tool_call=call), handler)
        assert not invoked
        code = classify_run_error(error.value)
        async with factory() as db:
            assert await end_run(db, run_id, "worker-a", "FAILED", code)
        async with factory() as db:
            run = await db.get(Run, run_id)
            tool = await db.scalar(select(ToolExecution).where(ToolExecution.run_id == run_id))
            assert (run.status, run.error_code, tool.status, tool.attempt) == (
                "FAILED",
                "TOOL_RESULT_UNAVAILABLE",
                "COMPLETED",
                1,
            )
    finally:
        await engine.dispose()


async def test_model_fact_does_not_persist_provider_extras_or_secret():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        journal = ModelCallJournal(factory, run_id, "worker-a", "deepseek", "flash")
        execution_id = await journal.start(
            f"{run_id}:model:1", "AGENT", [HumanMessage(content="问题")]
        )
        await journal.complete(
            execution_id,
            AIMessage(
                content="回答",
                additional_kwargs={
                    "reasoning_content": "私有思考",
                    "api_key": "sk-test-secret",
                },
                response_metadata={"finish_reason": "stop"},
                usage_metadata={"input_tokens": 4, "output_tokens": 2, "total_tokens": 6},
            ),
        )
        async with factory() as db:
            row = await db.get(ModelExecution, execution_id)
            assert row.output_message == {"role": "assistant", "content": "回答", "tool_calls": []}
            assert row.usage == {"input_tokens": 4, "output_tokens": 2, "total_tokens": 6}
            assert row.finish_reason == "stop"
            assert "私有思考" not in str(row.__dict__)
            assert "sk-test-secret" not in str(row.__dict__)
    finally:
        await engine.dispose()


async def test_tool_and_approval_timeline_refer_to_committed_facts():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory)
        store = ToolExecutionStore(factory, worker_id="worker-a")
        tool = await store.start(run_id, "call-1", "calculator", "READ_ONLY", "args-hash")
        await store.finish(run_id, "call-1", "COMPLETED", "4", None)
        async with factory() as db:
            approval = await ApprovalRepository(db).ensure(
                run_id, "call-2", "calculator", "确认", "执行计算", "LOW", worker_id="worker-a"
            )
        async with factory() as db:
            saved_tool = await db.get(ToolExecution, tool.id)
            saved_approval = await db.get(Approval, approval.id)
            timeline = list(
                await db.scalars(
                    select(RunTraceEvent)
                    .where(RunTraceEvent.run_id == run_id)
                    .order_by(RunTraceEvent.sequence)
                )
            )
            assert saved_tool.status == "COMPLETED"
            assert saved_approval.status == "PENDING"
            assert [
                (item.event_type, item.ref_id)
                for item in timeline
                if item.event_type != "activity.updated"
            ] == [
                ("tool.started", tool.id),
                ("tool.completed", tool.id),
                ("approval.required", approval.id),
            ]
    finally:
        await engine.dispose()


async def test_admin_timeline_is_compact_and_model_detail_requires_permission():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)

    async def override_db():
        async with factory() as db:
            yield db

    app.dependency_overrides[get_db] = override_db
    suffix = uuid4().hex[:8]
    try:
        run_id = await _running_run(factory)
        async with factory() as db:
            recorder = traces.ExecutionRecorder(db)
            model = await recorder.start_model(
                run_id,
                "worker-a",
                step_id=f"{run_id}:model:1",
                phase="AGENT",
                provider="openai",
                model_name="fake",
                input_messages=[{"role": "user", "content": "问题", "tool_calls": []}],
            )
            await db.commit()
        async with factory() as db:
            await traces.ExecutionRecorder(db).complete_model(
                model.id,
                "worker-a",
                {"role": "assistant", "content": "回答", "tool_calls": []},
            )
            await db.commit()
        async with factory() as db:
            view = await db.get(Permission, "run:view")
            if view is None:
                view = Permission(code="run:view")
                db.add(view)
            role = Role(name=f"timeline-reader-{suffix}", permissions=[view])
            db.add_all(
                [
                    User(
                        username=f"timeline-reader-{suffix}",
                        display_name="Timeline Reader",
                        password_hash=hash_password("reader-secret-123"),
                        roles=[role],
                    ),
                    User(
                        username=f"timeline-noaccess-{suffix}",
                        display_name="No Access",
                        password_hash=hash_password("reader-secret-123"),
                    ),
                ]
            )
            await db.commit()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as client:

            async def token(username):
                response = await client.post(
                    "/api/v1/auth/login",
                    json={"username": username, "password": "reader-secret-123"},
                )
                assert response.status_code == 200
                return {"Authorization": f"Bearer {response.json()['access_token']}"}

            allowed = await token(f"timeline-reader-{suffix}")
            denied = await token(f"timeline-noaccess-{suffix}")
            assert (
                await client.get(f"/api/v1/admin/runs/{run_id}/timeline", headers=denied)
            ).status_code == 403
            timeline = await client.get(f"/api/v1/admin/runs/{run_id}/timeline", headers=allowed)
            assert timeline.status_code == 200
            assert timeline.json()["total"] == 2
            item = timeline.json()["items"][-1]
            assert set(item) == {
                "sequence",
                "event_type",
                "attempt",
                "created_at",
                "ref_type",
                "ref_id",
                "duration",
                "summary",
            }
            assert "回答" not in timeline.text
            detail = await client.get(f"/api/v1/admin/model-executions/{model.id}", headers=allowed)
            assert detail.status_code == 200
            assert detail.json()["output_message"]["content"] == "回答"
    finally:
        app.dependency_overrides.clear()
        await engine.dispose()
