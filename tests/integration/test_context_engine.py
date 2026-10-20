import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.messages import AIMessage, HumanMessage
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.application.execution_spec import build_execution_spec
from app.context.errors import ContextLeaseLost, ContextStateMismatch, RunContextMissing
from app.execution.config import execution_spec_from_draft
from app.persistence.database import (
    AgentDefinition,
    ConversationSummary,
    Message,
    ModelConfig,
    ModelExecution,
    Run,
    RunContextSnapshot,
    RunTraceEvent,
    Session,
)
from app.worker.context_planning import prepare_v2_messages
from app.worker.model_recording import ModelCallJournal
from app.worker.runner import classify_run_error


async def test_summary_snapshot_survives_resume_and_keeps_messages():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    calls = {"count": 0}

    async def summarize(_prompt: str) -> str:
        calls["count"] += 1
        return "这是历史摘要"

    try:
        async with factory() as db:
            model = ModelConfig(
                name=f"context-model-{suffix}",
                provider="openai",
                model_name="fake",
                config={"context_window": 8000, "max_output_tokens": 1000},
            )
            db.add(model)
            await db.flush()
            agent = AgentDefinition(
                name=f"context-agent-{suffix}",
                model_id=model.id,
                system_prompt="测试助手",
                max_model_calls=3,
            )
            agent.tools = []
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="user")
            db.add(session)
            await db.flush()
            start = datetime(2026, 1, 1, tzinfo=UTC)
            messages = []
            for index in range(100):
                message = Message(
                    session_id=session.id,
                    user_id="user",
                    role="user" if index % 2 == 0 else "assistant",
                    content="历史" * 40,
                    created_at=start + timedelta(seconds=index),
                )
                messages.append(message)
            current = Message(
                session_id=session.id,
                user_id="user",
                role="user",
                content="当前问题保持完整",
                created_at=start + timedelta(seconds=100),
            )
            future = Message(
                session_id=session.id,
                user_id="user",
                role="user",
                content="之后才产生的消息",
                created_at=start + timedelta(seconds=200),
            )
            db.add_all([*messages, current, future])
            await db.flush()
            draft = build_execution_spec(agent, model)
            spec = execution_spec_from_draft(draft)
            db.add(spec)
            await db.flush()
            run = Run(
                session_id=session.id,
                message_id=current.id,
                status="RUNNING",
                lease_owner="worker-a",
                lease_until=datetime.now(UTC) + timedelta(minutes=5),
                execution_spec_id=spec.id,
                runtime_version=spec.runtime_version,
            )
            db.add(run)
            await db.commit()
            run_id = run.id
            session_id = session.id
            first_id = messages[0].id
            current_id = current.id
            future_id = future.id

        from app.execution.config import resolve_execution_config

        async with factory() as db:
            stored = await db.get(Run, run_id)
            spec = await db.get(type(spec), stored.execution_spec_id)
            config = resolve_execution_config(spec, None, None, None)

        _messages, resume = await prepare_v2_messages(
            run_id, "worker-a", config, None, summarize, factory
        )
        assert resume is False
        assert calls["count"] >= 1
        rendered = "\n".join(message.content for message in _messages)
        assert "当前问题保持完整" in rendered
        assert "之后才产生的消息" not in rendered

        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Message)
                    .where(Message.session_id == session_id)
                )
                == 102
            )
            snapshot = await db.scalar(
                select(RunContextSnapshot).where(RunContextSnapshot.run_id == run_id)
            )
            summary = await db.get(ConversationSummary, snapshot.summary_id)
            assert snapshot is not None
            assert first_id not in snapshot.message_ids
            assert current_id in snapshot.message_ids
            assert future_id not in snapshot.message_ids
            assert summary.revision == 1
            assert summary.source_message_count >= 1
            snapshot_id = snapshot.id
            message_count = await db.scalar(
                select(func.count()).select_from(Message).where(Message.session_id == session_id)
            )

        async def fail_if_called(_prompt: str) -> str:
            raise AssertionError("恢复不应重新摘要")

        again, _resume = await prepare_v2_messages(
            run_id, "worker-b", config, None, fail_if_called, factory
        )
        assert any(message.content == "当前问题保持完整" for message in again)
        async with factory() as db:
            snapshots = list(
                await db.scalars(
                    select(RunContextSnapshot).where(RunContextSnapshot.run_id == run_id)
                )
            )
            assert [item.id for item in snapshots] == [snapshot_id]
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(Message)
                    .where(Message.session_id == session_id)
                )
                == message_count
            )
    finally:
        await engine.dispose()


async def test_lease_loss_does_not_write_snapshot_and_checkpoint_skips_planning():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        run_id, config = await _seed_run(factory, suffix, lease_owner="worker-b")

        async def summarize(_prompt: str) -> str:
            return "不应落库"

        with pytest.raises(ContextLeaseLost):
            await prepare_v2_messages(run_id, "worker-a", config, None, summarize, factory)
        async with factory() as db:
            session_id = await db.scalar(select(Run.session_id).where(Run.id == run_id))
            assert (
                await db.scalar(
                    select(RunContextSnapshot).where(RunContextSnapshot.run_id == run_id)
                )
            ) is None
            assert (
                await db.scalar(
                    select(func.count())
                    .select_from(ConversationSummary)
                    .where(ConversationSummary.session_id == session_id)
                )
            ) == 0

        class Saver:
            async def aget_tuple(self, _config):
                return object()

        async def unexpected(_prompt: str) -> str:
            raise AssertionError("已有检查点时不应规划")

        messages, resume = await prepare_v2_messages(
            run_id, "worker-b", config, Saver(), unexpected, factory
        )
        assert messages == []
        assert resume is True
        async with factory() as db:
            assert (
                await db.scalar(
                    select(RunContextSnapshot).where(RunContextSnapshot.run_id == run_id)
                )
            ) is None
    finally:
        await engine.dispose()


async def test_summary_attempt_before_snapshot_does_not_block_replanning():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id, config = await _seed_run(factory, uuid4().hex[:8], lease_owner="worker-a")
        journal = ModelCallJournal(factory, run_id, "worker-a", "openai", "fake")
        execution_id = await journal.start(
            f"{run_id}:summary:1", "CONTEXT_SUMMARY", [HumanMessage(content="待摘要历史")]
        )
        await journal.complete(execution_id, AIMessage(content="历史摘要"))
        async with factory() as db:
            execution = await db.get(ModelExecution, execution_id)
            assert execution.phase == "CONTEXT_SUMMARY"
            assert execution.status == "COMPLETED"
            assert execution.output_message["content"] == "历史摘要"
            kinds = list(
                await db.scalars(
                    select(RunTraceEvent.event_type)
                    .where(RunTraceEvent.run_id == run_id)
                    .order_by(RunTraceEvent.sequence)
                )
            )
            assert kinds == ["context_summary.started", "context_summary.completed"]

        async def summarize(_prompt: str) -> str:
            return "历史摘要"

        messages, resumed = await prepare_v2_messages(
            run_id, "worker-a", config, None, summarize, factory
        )
        assert resumed is False
        assert any(message.content == "当前" for message in messages)
    finally:
        await engine.dispose()


async def test_completed_working_summary_replays_only_for_same_input_and_active_lease():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id, _config = await _seed_run(factory, uuid4().hex[:8], lease_owner="worker-a")
        journal = ModelCallJournal(factory, run_id, "worker-a", "openai", "fake")
        step_id = f"{run_id}:working:4:source"
        prompt = [HumanMessage(content="待压缩历史")]
        assert await journal.completed_summary(step_id, prompt) is None
        execution_id = await journal.start(step_id, "CONTEXT_SUMMARY", prompt)
        await journal.complete(execution_id, AIMessage(content="已保存摘要"))
        assert await journal.completed_summary(step_id, prompt) == "已保存摘要"
        with pytest.raises(ContextStateMismatch, match="摘要输入不一致"):
            await journal.completed_summary(step_id, [HumanMessage(content="不同输入")])
        stale = ModelCallJournal(factory, run_id, "worker-b", "openai", "fake")
        with pytest.raises(ContextLeaseLost):
            await stale.completed_summary(step_id, prompt)
    finally:
        await engine.dispose()


async def test_changed_message_content_does_not_match_snapshot_hash():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]

    async def summarize(_prompt: str) -> str:
        return "短摘要"

    try:
        run_id, config = await _seed_run(factory, suffix, lease_owner="worker-a")
        await prepare_v2_messages(run_id, "worker-a", config, None, summarize, factory)
        async with factory() as db:
            snapshot = await db.scalar(
                select(RunContextSnapshot).where(RunContextSnapshot.run_id == run_id)
            )
            message = await db.get(Message, snapshot.message_ids[-1])
            message.content = "正文被改掉"
            await db.commit()
        with pytest.raises(RunContextMissing):
            await prepare_v2_messages(run_id, "worker-a", config, None, summarize, factory)
    finally:
        await engine.dispose()


async def test_started_run_without_snapshot_or_checkpoint_is_missing():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        run_id, config = await _seed_run(factory, suffix, lease_owner="worker-a")
        async with factory() as db:
            db.add(RunTraceEvent(run_id=run_id, sequence=1, event_type="model.started", data={}))
            await db.commit()
        with pytest.raises(RunContextMissing) as caught:
            await prepare_v2_messages(run_id, "worker-a", config, None, _no_summary, factory)
        assert classify_run_error(caught.value) == "RUN_CONTEXT_MISSING"
    finally:
        await engine.dispose()


async def _seed_run(factory, suffix: str, lease_owner: str):
    async with factory() as db:
        model = ModelConfig(
            name=f"lease-model-{suffix}",
            provider="openai",
            model_name="fake",
            config={"context_window": 8000, "max_output_tokens": 1000},
        )
        db.add(model)
        await db.flush()
        agent = AgentDefinition(
            name=f"lease-agent-{suffix}", model_id=model.id, system_prompt="测试", max_model_calls=2
        )
        agent.tools = []
        db.add(agent)
        await db.flush()
        session = Session(agent_id=agent.id, user_id="user")
        db.add(session)
        await db.flush()
        start = datetime(2026, 2, 1, tzinfo=UTC)
        rows = []
        for index in range(30):
            rows.append(
                Message(
                    session_id=session.id,
                    user_id="user",
                    role="user",
                    content="历史" * 40,
                    created_at=start + timedelta(seconds=index),
                )
            )
        current = Message(
            session_id=session.id,
            user_id="user",
            role="user",
            content="当前",
            created_at=start + timedelta(seconds=30),
        )
        db.add_all([*rows, current])
        await db.flush()
        spec = execution_spec_from_draft(build_execution_spec(agent, model))
        db.add(spec)
        await db.flush()
        run = Run(
            session_id=session.id,
            message_id=current.id,
            status="RUNNING",
            lease_owner=lease_owner,
            lease_until=datetime.now(UTC) + timedelta(minutes=5),
            execution_spec_id=spec.id,
        )
        db.add(run)
        await db.commit()
        from app.execution.config import resolve_execution_config

        config = resolve_execution_config(spec, None, None, None)
        return run.id, config


async def _no_summary(_prompt: str) -> str:
    raise AssertionError("缺失上下文时不应摘要")
