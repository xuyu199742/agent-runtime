import asyncio
import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.domain.budget import ExecutionBudget
from app.persistence.database import (
    AgentDefinition,
    EffectRecord,
    Message,
    ModelConfig,
    ModelExecution,
    Run,
    RunTraceEvent,
    Session,
    ToolExecution,
)
from app.persistence.repositories.effects import EffectStore
from app.persistence.repositories.runs import end_run
from app.persistence.repositories.tool_executions import ToolExecutionStore
from app.runtime.agent import LangChainAgentRuntime
from app.runtime.budget import (
    BudgetExternalWritesExceeded,
    BudgetModelCallsExceeded,
    BudgetToolCallsExceeded,
    RunDeadlineExceeded,
)
from app.runtime.effects.contract import EffectIdentity, EffectObservation
from app.runtime.effects.executor import EffectExecutor
from app.worker.model_recording import ModelCallJournal


async def _run(factory, worker="worker-a"):
    suffix = uuid4().hex
    async with factory() as db:
        model = ModelConfig(name=f"budget-model-{suffix}", provider="openai", model_name="fake")
        db.add(model)
        await db.flush()
        agent = AgentDefinition(name=f"budget-agent-{suffix}", model_id=model.id)
        db.add(agent)
        await db.flush()
        session = Session(agent_id=agent.id, user_id=f"budget-user-{suffix}")
        db.add(session)
        await db.flush()
        message = Message(session_id=session.id, user_id=session.user_id, role="user", content="hi")
        db.add(message)
        await db.flush()
        run = Run(
            session_id=session.id,
            message_id=message.id,
            status="RUNNING",
            lease_owner=worker,
            lease_until=datetime.now(UTC) + timedelta(seconds=45),
        )
        db.add(run)
        await db.commit()
        return run.id


async def test_tool_budget_counts_unique_logical_calls_and_replay():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        store = ToolExecutionStore(factory, "worker-a", ExecutionBudget(5, 2, 1, 3600))
        await store.start(run_id, "call-1", "echo", "READ_ONLY", "a" * 64)
        await store.start(run_id, "call-2", "echo", "READ_ONLY", "b" * 64)
        await store.start(run_id, "call-1", "echo", "READ_ONLY", "a" * 64)
        with pytest.raises(BudgetToolCallsExceeded):
            await store.start(run_id, "call-3", "echo", "READ_ONLY", "c" * 64)
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count(ToolExecution.id)).where(ToolExecution.run_id == run_id)
                )
                == 2
            )
    finally:
        await engine.dispose()


async def test_two_parallel_calls_compete_for_last_tool_slot():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        store = ToolExecutionStore(factory, "worker-a", ExecutionBudget(5, 1, 0, 3600))
        outcomes = await asyncio.gather(
            store.start(run_id, "parallel-1", "echo", "READ_ONLY", "a" * 64),
            store.start(run_id, "parallel-2", "echo", "READ_ONLY", "b" * 64),
            return_exceptions=True,
        )
        assert sum(isinstance(item, ToolExecution) for item in outcomes) == 1
        assert sum(isinstance(item, BudgetToolCallsExceeded) for item in outcomes) == 1
    finally:
        await engine.dispose()


async def test_runtime_tool_budget_stops_second_tool_before_execution():
    class ToolCallingModel(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    invoked = 0

    async def echo(value: str) -> str:
        nonlocal invoked
        invoked += 1
        return value

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    try:
        run_id = await _run(factory)
        model = ToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[
                        {"name": "echo", "args": {"value": "a"}, "id": "call-1"},
                        {"name": "echo", "args": {"value": "b"}, "id": "call-2"},
                    ],
                ),
                AIMessage(content="done"),
            ]
        )
        runtime = LangChainAgentRuntime(
            model,
            [StructuredTool.from_function(coroutine=echo, name="echo", description="echo")],
            "",
            5,
            tool_execution_store=ToolExecutionStore(
                factory, "worker-a", ExecutionBudget(5, 1, 0, 3600)
            ),
            run_id=run_id,
            tool_policies={"echo": {"effect_type": "READ_ONLY", "enabled": True}},
            worker_id="worker-a",
        )
        with pytest.raises(BudgetToolCallsExceeded):
            await runtime.run(run_id, [HumanMessage(content="echo")], emit, not_cancelled)
        assert invoked == 1
    finally:
        await engine.dispose()


async def test_model_budget_counts_unique_agent_steps_and_excludes_summary():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        journal = ModelCallJournal(
            factory, run_id, "worker-a", "openai", "fake", ExecutionBudget(1, 5, 0, 3600)
        )
        message = [HumanMessage(content="hello")]
        await journal.start("summary-1", "CONTEXT_SUMMARY", message)
        await journal.start("step-1", "AGENT", message)
        await journal.start("step-1", "AGENT", message)
        with pytest.raises(BudgetModelCallsExceeded):
            await journal.start("step-2", "AGENT", message)
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count(func.distinct(ModelExecution.step_id))).where(
                        ModelExecution.run_id == run_id, ModelExecution.phase == "AGENT"
                    )
                )
                == 1
            )
    finally:
        await engine.dispose()


async def test_external_write_budget_checks_at_dispatch_and_preserves_prepared():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        store = EffectStore(factory, ExecutionBudget(5, 3, 1, 3600))
        first = await store.prepare(
            run_id, "worker-a", "budget-test", "write", uuid4().hex, 1, "a" * 64, "call-1"
        )
        assert await store.claim_dispatch(first.id, run_id, "worker-a")
        assert not await store.claim_dispatch(first.id, run_id, "worker-a")
        second = await store.prepare(
            run_id, "worker-a", "budget-test", "write", uuid4().hex, 1, "b" * 64, "call-2"
        )
        with pytest.raises(BudgetExternalWritesExceeded):
            await store.claim_dispatch(second.id, run_id, "worker-a")
        async with factory() as db:
            assert (await db.get(EffectRecord, second.id)).status == "PREPARED"
    finally:
        await engine.dispose()


async def test_external_budget_denial_never_invokes_provider():
    class Provider:
        def __init__(self):
            self.calls = 0

        def identity(self, args):
            return EffectIdentity("budget-provider", "write", args["key"], 1, "e" * 64)

        async def invoke(self, args, business_key):
            self.calls += 1
            return EffectObservation.succeeded("ok", business_key)

    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        provider = Provider()
        executor = EffectExecutor(EffectStore(factory, ExecutionBudget(5, 2, 1, 3600)), provider)
        assert (
            await executor.execute(run_id, "worker-a", {"key": uuid4().hex}, call_id="call-1")
            == "ok"
        )
        with pytest.raises(BudgetExternalWritesExceeded):
            await executor.execute(run_id, "worker-a", {"key": uuid4().hex}, call_id="call-2")
        assert provider.calls == 1
    finally:
        await engine.dispose()


async def test_dispatched_effect_can_be_reconciled_after_deadline():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        store = EffectStore(factory, ExecutionBudget(5, 2, 1, 1))
        effect = await store.prepare(
            run_id, "worker-a", "budget-test", "write", uuid4().hex, 1, "c" * 64, "call-1"
        )
        assert await store.claim_dispatch(effect.id, run_id, "worker-a")
        async with factory() as db:
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    created_at=datetime.now(UTC) - timedelta(seconds=2),
                    lease_owner="worker-b",
                )
            )
            await db.commit()
        recovered = await store.prepare(
            run_id,
            "worker-b",
            "budget-test",
            "write",
            effect.business_key,
            1,
            "c" * 64,
            "call-1",
        )
        assert recovered.status == "DISPATCHED"
        await store.advance(effect.id, run_id, "worker-b", "unknown")
        assert await store.begin_reconcile(effect.id, run_id, "worker-b")
    finally:
        await engine.dispose()


async def test_cross_run_effect_reuse_only_consumes_tool_budget():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        first_run = await _run(factory, "worker-a")
        second_run = await _run(factory, "worker-b")
        business_key = uuid4().hex
        first_store = EffectStore(factory, ExecutionBudget(5, 2, 1, 3600))
        first = await first_store.prepare(
            first_run, "worker-a", "budget-test", "write", business_key, 1, "d" * 64, "call-a"
        )
        assert await first_store.claim_dispatch(first.id, first_run, "worker-a")
        await first_store.advance(
            first.id,
            first_run,
            "worker-a",
            "observed_success",
            result_content="ok",
            call_id="call-a",
        )
        second_store = EffectStore(factory, ExecutionBudget(5, 1, 0, 3600))
        reused = await second_store.prepare(
            second_run,
            "worker-b",
            "budget-test",
            "write",
            business_key,
            1,
            "d" * 64,
            "call-b",
        )
        assert reused.status == "SUCCEEDED"
        assert not await second_store.claim_dispatch(reused.id, second_run, "worker-b")
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count(ToolExecution.id)).where(ToolExecution.run_id == second_run)
                )
                == 1
            )
            assert (
                await db.scalar(
                    select(func.count(EffectRecord.id)).where(
                        EffectRecord.dispatch_run_id == second_run
                    )
                )
                == 0
            )
    finally:
        await engine.dispose()


async def test_expired_run_rejects_model_call_before_recording_it():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        async with factory() as db:
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(created_at=datetime.now(UTC) - timedelta(seconds=2))
            )
            await db.commit()
        journal = ModelCallJournal(
            factory, run_id, "worker-a", "openai", "fake", ExecutionBudget(1, 1, 0, 1)
        )
        with pytest.raises(RunDeadlineExceeded):
            await journal.start("step-1", "AGENT", [HumanMessage(content="hello")])
        async with factory() as db:
            assert (
                await db.scalar(
                    select(func.count(ModelExecution.id)).where(ModelExecution.run_id == run_id)
                )
                == 0
            )
    finally:
        await engine.dispose()


async def test_expired_run_rejects_new_tool_and_records_budget_failure():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _run(factory)
        async with factory() as db:
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(created_at=datetime.now(UTC) - timedelta(seconds=2))
            )
            await db.commit()
        store = ToolExecutionStore(factory, "worker-a", ExecutionBudget(5, 1, 0, 1))
        with pytest.raises(RunDeadlineExceeded) as captured:
            await store.start(run_id, "expired-call", "echo", "READ_ONLY", "a" * 64)
        async with factory() as db:
            assert await end_run(
                db, run_id, "worker-a", "FAILED", captured.value.code, captured.value.event_data()
            )
        async with factory() as db:
            run = await db.get(Run, run_id)
            events = (
                await db.scalars(
                    select(RunTraceEvent)
                    .where(RunTraceEvent.run_id == run_id)
                    .order_by(RunTraceEvent.sequence)
                )
            ).all()
            assert run.error_code == "RUN_DEADLINE_EXCEEDED"
            assert [event.event_type for event in events] == ["budget.exceeded", "run.failed"]
            assert events[0].data["dimension"] == "deadline"
    finally:
        await engine.dispose()
