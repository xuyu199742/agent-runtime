import asyncio
import os
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langchain_core.tools import StructuredTool
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.context.errors import ContextLeaseLost
from app.persistence.database import (
    AgentDefinition,
    Approval,
    EffectRecord,
    Message,
    ModelConfig,
    Run,
    RunTraceEvent,
    Session,
    ToolExecution,
)
from app.persistence.repositories.effects import EffectStore
from app.runtime.agent import LangChainAgentRuntime
from app.runtime.effects.contract import EffectIdentity, EffectObservation
from app.runtime.effects.executor import EffectExecutor
from app.runtime.errors import EffectManualRequired, EffectNotApplied, EffectUncertain, PolicyDenied
from app.runtime.middleware import PolicyMiddleware


async def _running_run(factory, worker_id):
    suffix = uuid4().hex
    async with factory() as db:
        model = ModelConfig(name=f"executor-model-{suffix}", provider="openai", model_name="fake")
        db.add(model)
        await db.flush()
        agent = AgentDefinition(name=f"executor-agent-{suffix}", model_id=model.id)
        db.add(agent)
        await db.flush()
        session = Session(agent_id=agent.id, user_id=f"executor-user-{suffix}")
        db.add(session)
        await db.flush()
        message = Message(
            session_id=session.id, user_id=session.user_id, role="user", content="ticket"
        )
        db.add(message)
        await db.flush()
        run = Run(
            session_id=session.id,
            message_id=message.id,
            status="RUNNING",
            lease_owner=worker_id,
            lease_until=datetime.now(UTC) + timedelta(seconds=45),
        )
        db.add(run)
        await db.commit()
        return run.id


class FakeTicketProvider:
    def __init__(self):
        self.ledger = {}
        self.calls = 0
        self.drop_response = True

    def identity(self, args):
        key = f"ticket:create:{args['ticket_key']}"
        return EffectIdentity("account-a", "ticket.create", key, 1, args["request_hash"])

    async def invoke(self, args, business_key):
        self.calls += 1
        self.ledger.setdefault(business_key, '{"ticket_id":"T-1"}')
        if self.drop_response:
            raise TimeoutError("响应丢失")
        return EffectObservation.succeeded(self.ledger[business_key], "T-1")

    async def reconcile(self, identity):
        content = self.ledger.get(identity.business_key)
        if content is None:
            return EffectObservation.unknown()
        return EffectObservation.succeeded(content, "T-1")


class ToolCallingModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def test_response_loss_is_reconciled_and_retry_run_replays_result():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "a" * 64}
    try:
        first_run = await _running_run(factory, "worker-a")
        second_run = await _running_run(factory, "worker-b")
        executor = EffectExecutor(EffectStore(factory), provider)
        assert await executor.execute(first_run, "worker-a", args) == '{"ticket_id":"T-1"}'
        assert await executor.execute(second_run, "worker-b", args) == '{"ticket_id":"T-1"}'
        assert provider.calls == 1
        assert len(provider.ledger) == 1
    finally:
        await engine.dispose()


async def test_agent_receives_reconciled_tool_result_without_invoking_raw_tool():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "b" * 64}
    invoked_raw_tool = False

    async def raw_tool(ticket_key: str, request_hash: str) -> str:
        nonlocal invoked_raw_tool
        invoked_raw_tool = True
        raise AssertionError("写入必须由 Effect Executor 执行")

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    try:
        run_id = await _running_run(factory, "worker-a")
        model = ToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ticket.create", "args": args, "id": "call-ticket"}],
                ),
                AIMessage(content="工单 T-1 已创建"),
            ]
        )
        tool = StructuredTool.from_function(
            coroutine=raw_tool, name="ticket.create", description="创建受控工单"
        )
        runtime = LangChainAgentRuntime(
            model,
            [tool],
            "",
            5,
            tool_execution_store=None,
            run_id=run_id,
            tool_policies={
                "ticket.create": {
                    "effect_type": "EXTERNAL_WRITE",
                    "policy": {"write_allowed": True},
                }
            },
            effect_store=EffectStore(factory),
            effect_providers={"ticket.create": provider},
            worker_id="worker-a",
        )
        answer = await runtime.run(run_id, [HumanMessage(content="创建工单")], emit, not_cancelled)
        assert answer == "工单 T-1 已创建"
        assert provider.calls == 1
        assert not invoked_raw_tool
        async with factory() as db:
            call = await db.scalar(
                select(ToolExecution).where(
                    ToolExecution.run_id == run_id, ToolExecution.tool_call_id == "call-ticket"
                )
            )
            assert call is not None
            assert call.status == "COMPLETED"
            assert call.result_content == '{"ticket_id":"T-1"}'
            effect = await db.get(EffectRecord, call.effect_id)
            assert effect.status == "SUCCEEDED"
    finally:
        await engine.dispose()


async def test_lost_worker_cannot_commit_success_and_new_owner_reconciles():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "c" * 64}
    try:
        run_id = await _running_run(factory, "worker-a")

        async def invoke_then_lose_lease(arguments, business_key):
            provider.calls += 1
            provider.ledger[business_key] = '{"ticket_id":"T-1"}'
            async with factory() as db:
                await db.execute(
                    update(Run)
                    .where(Run.id == run_id)
                    .values(
                        lease_owner="worker-b",
                        lease_until=datetime.now(UTC) + timedelta(seconds=45),
                    )
                )
                await db.commit()
            raise TimeoutError("旧 Worker 丢失结果")

        provider.invoke = invoke_then_lose_lease
        executor = EffectExecutor(EffectStore(factory), provider)
        try:
            await executor.execute(run_id, "worker-a", args)
            raise AssertionError("旧 Worker 不得提交结果")
        except ContextLeaseLost:
            pass
        assert await executor.execute(run_id, "worker-b", args) == '{"ticket_id":"T-1"}'
        assert provider.calls == 1
    finally:
        await engine.dispose()


async def test_nonfinal_not_applied_never_becomes_failed():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "d" * 64}

    async def not_applied_yet(_identity):
        return EffectObservation.not_applied(final=False)

    provider.reconcile = not_applied_yet
    try:
        run_id = await _running_run(factory, "worker-a")
        executor = EffectExecutor(EffectStore(factory), provider)
        try:
            await executor.execute(run_id, "worker-a", args)
            raise AssertionError("未具最终性的查询不能视为失败")
        except EffectManualRequired:
            pass
        async with factory() as db:
            effect = await db.scalar(
                select(EffectRecord).where(
                    EffectRecord.business_key == f"ticket:create:{args['ticket_key']}"
                )
            )
            assert effect.status == "MANUAL_REQUIRED"
    finally:
        await engine.dispose()


async def test_dispatched_before_send_is_only_reconciled_after_lease_transfer():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    key = f"warning-{uuid4().hex}"
    args = {"ticket_key": key, "request_hash": "e" * 64}
    try:
        run_id = await _running_run(factory, "worker-a")
        store = EffectStore(factory)
        identity = provider.identity(args)
        effect = await store.prepare(
            run_id,
            "worker-a",
            identity.provider_namespace,
            identity.operation_name,
            identity.business_key,
            identity.contract_version,
            identity.request_hash,
        )
        assert await store.claim_dispatch(effect.id, run_id, "worker-a")
        async with factory() as db:
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    lease_owner="worker-b", lease_until=datetime.now(UTC) + timedelta(seconds=45)
                )
            )
            await db.commit()
        with pytest.raises(EffectManualRequired):
            await EffectExecutor(store, provider).execute(run_id, "worker-b", args)
        assert provider.calls == 0
        async with factory() as db:
            current = await db.get(EffectRecord, effect.id)
            assert current.status == "MANUAL_REQUIRED"
    finally:
        await engine.dispose()


async def test_remote_success_before_local_commit_is_reconciled_without_resend():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    key = f"warning-{uuid4().hex}"
    args = {"ticket_key": key, "request_hash": "f" * 64}
    try:
        run_id = await _running_run(factory, "worker-a")
        store = EffectStore(factory)
        identity = provider.identity(args)
        effect = await store.prepare(
            run_id,
            "worker-a",
            identity.provider_namespace,
            identity.operation_name,
            identity.business_key,
            identity.contract_version,
            identity.request_hash,
        )
        assert await store.claim_dispatch(effect.id, run_id, "worker-a")
        provider.drop_response = False
        await provider.invoke(args, identity.business_key)
        # 模拟 Provider 已返回，但 Worker 在写入 SUCCEEDED 前崩溃。
        async with factory() as db:
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    lease_owner="worker-b", lease_until=datetime.now(UTC) + timedelta(seconds=45)
                )
            )
            await db.commit()
        result = await EffectExecutor(store, provider).execute(run_id, "worker-b", args)
        assert result == '{"ticket_id":"T-1"}'
        assert provider.calls == 1
    finally:
        await engine.dispose()


async def test_final_not_applied_is_failed_without_resend():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "1" * 64}

    async def rejected_before_commit(_args, _business_key):
        provider.calls += 1
        raise TimeoutError("请求已被服务端终止，随后由核对接口提供最终性证明")

    async def definitively_absent(_identity):
        return EffectObservation.not_applied(final=True)

    provider.reconcile = definitively_absent
    provider.invoke = rejected_before_commit
    try:
        run_id = await _running_run(factory, "worker-a")
        with pytest.raises(EffectNotApplied):
            await EffectExecutor(EffectStore(factory), provider).execute(run_id, "worker-a", args)
        assert provider.calls == 1
        async with factory() as db:
            effect = await db.scalar(
                select(EffectRecord).where(
                    EffectRecord.business_key == f"ticket:create:{args['ticket_key']}"
                )
            )
            assert effect.status == "FAILED"
            assert effect.error_code == "EFFECT_NOT_APPLIED"
    finally:
        await engine.dispose()


async def test_unknown_write_blocks_model_continuation():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "2" * 64}

    async def unknown(_identity):
        return EffectObservation.unknown()

    provider.reconcile = unknown

    async def raw_tool(ticket_key: str, request_hash: str) -> str:
        raise AssertionError("原始写入 Tool 不可调用")

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    try:
        run_id = await _running_run(factory, "worker-a")
        model = ToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ticket.create", "args": args, "id": "call-unknown"}],
                ),
                AIMessage(content="模型不应收到未知写入后的消息"),
            ]
        )
        runtime = LangChainAgentRuntime(
            model,
            [
                StructuredTool.from_function(
                    coroutine=raw_tool, name="ticket.create", description="受控写入"
                )
            ],
            "",
            5,
            run_id=run_id,
            tool_policies={
                "ticket.create": {
                    "effect_type": "EXTERNAL_WRITE",
                    "policy": {"write_allowed": True},
                }
            },
            effect_store=EffectStore(factory),
            effect_providers={"ticket.create": provider},
            worker_id="worker-a",
        )
        with pytest.raises(EffectManualRequired):
            await runtime.run(run_id, [HumanMessage(content="创建工单")], emit, not_cancelled)
        assert provider.calls == 1
    finally:
        await engine.dispose()


async def test_reconcile_can_be_taken_over_after_same_run_changes_worker():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory, "worker-a")
        store = EffectStore(factory)
        effect = await store.prepare(
            run_id,
            "worker-a",
            "account-a",
            "ticket.create",
            f"ticket:create:{uuid4().hex}",
            1,
            "3" * 64,
        )
        assert await store.claim_dispatch(effect.id, run_id, "worker-a")
        await store.advance(effect.id, run_id, "worker-a", "unknown")
        assert await store.begin_reconcile(effect.id, run_id, "worker-a")
        async with factory() as db:
            await db.execute(
                update(Run)
                .where(Run.id == run_id)
                .values(
                    lease_owner="worker-b", lease_until=datetime.now(UTC) + timedelta(seconds=45)
                )
            )
            await db.commit()
        assert await store.begin_reconcile(effect.id, run_id, "worker-b")
        with pytest.raises(ContextLeaseLost):
            await store.advance(
                effect.id, run_id, "worker-a", "observed_success", result_content="stale"
            )
    finally:
        await engine.dispose()


async def test_same_run_same_call_concurrent_entry_never_dispatches_twice():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    entered = asyncio.Event()
    release = asyncio.Event()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "4" * 64}

    async def slow_invoke(_args, business_key):
        provider.calls += 1
        entered.set()
        await release.wait()
        provider.ledger[business_key] = '{"ticket_id":"T-1"}'
        return EffectObservation.succeeded(provider.ledger[business_key], "T-1")

    provider.invoke = slow_invoke
    try:
        run_id = await _running_run(factory, "worker-a")
        executor = EffectExecutor(EffectStore(factory), provider)
        first = asyncio.create_task(executor.execute(run_id, "worker-a", args, call_id="same-call"))
        await asyncio.wait_for(entered.wait(), timeout=2)
        with pytest.raises(EffectUncertain):
            await executor.execute(run_id, "worker-a", args, call_id="same-call")
        assert provider.calls == 1
        release.set()
        assert await first == '{"ticket_id":"T-1"}'
    finally:
        release.set()
        await engine.dispose()


async def test_rejected_write_approval_creates_no_effect_or_provider_request(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    provider = FakeTicketProvider()
    args = {"ticket_key": f"warning-{uuid4().hex}", "request_hash": "5" * 64}

    async def raw_tool(ticket_key: str, request_hash: str) -> str:
        raise AssertionError("审批拒绝后不可进入原始 Tool")

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    monkeypatch.setattr("app.runtime.approval.interrupt", lambda _payload: False)
    try:
        run_id = await _running_run(factory, "worker-a")
        model = ToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "ticket.create", "args": args, "id": "call-rejected"}],
                ),
                AIMessage(content="已拒绝"),
            ]
        )
        runtime = LangChainAgentRuntime(
            model,
            [
                StructuredTool.from_function(
                    coroutine=raw_tool, name="ticket.create", description="受控工单"
                )
            ],
            "",
            5,
            run_id=run_id,
            tool_policies={
                "ticket.create": {
                    "name": "ticket.create",
                    "effect_type": "EXTERNAL_WRITE",
                    "policy": {"write_allowed": True, "requires_approval": True},
                }
            },
            approval_session_factory=factory,
            effect_store=EffectStore(factory),
            effect_providers={"ticket.create": provider},
            worker_id="worker-a",
        )
        assert (
            await runtime.run(run_id, [HumanMessage(content="创建工单")], emit, not_cancelled)
            == "已拒绝"
        )
        async with factory() as db:
            assert await db.scalar(select(Approval).where(Approval.run_id == run_id)) is not None
            assert (
                await db.scalar(select(EffectRecord).where(EffectRecord.origin_run_id == run_id))
                is None
            )
            assert (
                await db.scalar(select(ToolExecution).where(ToolExecution.run_id == run_id)) is None
            )
        assert provider.calls == 0
        assert provider.ledger == {}
    finally:
        await engine.dispose()


async def test_policy_denial_is_recorded_without_approval_or_effect():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        run_id = await _running_run(factory, "worker-a")
        middleware = PolicyMiddleware(
            factory,
            run_id,
            "worker-a",
            {
                "ticket.create": {
                    "name": "ticket.create",
                    "effect_type": "EXTERNAL_WRITE",
                    "policy": {"write_allowed": False, "requires_approval": True},
                }
            },
        )

        async def handler(_request):
            raise AssertionError("拒绝后不应进入审批或 Effect")

        request = SimpleNamespace(
            tool_call={"name": "ticket.create", "id": "denied", "args": {"secret": "x"}}
        )
        with pytest.raises(PolicyDenied) as exc:
            await middleware.awrap_tool_call(request, handler)
        assert exc.value.code == "WRITE_NOT_ALLOWED"
        async with factory() as db:
            event = await db.scalar(select(RunTraceEvent).where(RunTraceEvent.run_id == run_id))
            assert event.event_type == "policy.denied"
            assert event.data == {
                "name": "ticket.create",
                "reason_code": "WRITE_NOT_ALLOWED",
                "effect_type": "EXTERNAL_WRITE",
            }
            assert await db.scalar(select(Approval).where(Approval.run_id == run_id)) is None
            assert (
                await db.scalar(select(EffectRecord).where(EffectRecord.origin_run_id == run_id))
                is None
            )
    finally:
        await engine.dispose()
