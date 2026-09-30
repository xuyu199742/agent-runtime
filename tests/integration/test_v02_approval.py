import os
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage
from redis.asyncio import Redis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.messaging.events import EventStore
from app.messaging.run_queue import RunQueue
from app.persistence.database import (
    AgentDefinition,
    Approval,
    Message,
    ModelConfig,
    Run,
    Session,
    ToolDefinition,
    ToolExecution,
)
from app.persistence.repositories.approvals import ApprovalRepository
from app.persistence.repositories.conversations import ConversationRepository
from app.runtime.checkpoint import create_checkpoint_pool, create_saver
from app.worker import runner


class ApprovalModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


@pytest.mark.parametrize("approve", [True, False])
async def test_tool_approval_waits_then_resumes_from_checkpoint(monkeypatch, approve):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    suffix = uuid4().hex[:8]
    queue = RunQueue(redis, stream=f"test:approval:{suffix}", group=f"test-approval-{suffix}")
    model = ApprovalModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "echo", "args": {"text": "ok"}, "id": "approval-call"}],
            ),
            AIMessage(content="approved answer"),
        ]
    )
    run_id = None
    tool_id = None
    old_policy = {}
    try:
        async with factory() as db:
            model_config = ModelConfig(
                name=f"approval-model-{suffix}", provider="openai", model_name="fake"
            )
            tool = await db.scalar(select(ToolDefinition).where(ToolDefinition.name == "echo"))
            if tool is None:
                tool = ToolDefinition(
                    name="echo", type="NATIVE", policy={"requires_approval": True}
                )
                db.add(tool)
            else:
                old_policy = dict(tool.policy)
                tool.policy = {"requires_approval": True}
            await db.flush()
            tool_id = tool.id
            db.add(model_config)
            await db.flush()
            agent = AgentDefinition(
                name=f"approval-agent-{suffix}", model_id=model_config.id, tools=[tool]
            )
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="approval-user")
            db.add(session)
            await db.commit()
        async with factory() as db:
            accepted = await ConversationRepository(db).create_submission(
                session.id, "approval-user", f"approval-{suffix}", "ask approval"
            )
            run_id = accepted[1]

        monkeypatch.setattr(runner, "session_factory", factory)
        monkeypatch.setattr(runner, "build_model", lambda _config: model)
        pool = create_checkpoint_pool(os.environ["TEST_CHECKPOINT_DATABASE_URL"], concurrency=2)
        async with pool:
            saver = create_saver(pool)
            await saver.setup()
            await queue.ensure_group()
            await queue.enqueue(run_id)
            entry = (await queue.read("approval-worker", block_ms=100))[0]
            await runner.process_entry(
                *entry, "approval-worker", redis, queue, EventStore(redis), saver
            )
            async with factory() as db:
                run = await db.get(Run, run_id)
                approval = (await ApprovalRepository(db).for_run(run_id))[0]
                assert run.status == "WAITING"
                assert approval.status == "PENDING"
                assert (
                    await db.scalar(select(ToolExecution).where(ToolExecution.run_id == run_id))
                    is None
                )
                approval_id = approval.id

            async with factory() as db:
                await ApprovalRepository(db).decide(approval_id, "approval-user", approve)
            await queue.enqueue(run_id)
            resumed = (await queue.read("approval-worker", block_ms=100))[0]
            await runner.process_entry(
                *resumed, "approval-worker", redis, queue, EventStore(redis), saver
            )

        async with factory() as db:
            run = await db.get(Run, run_id)
            execution = await db.scalar(select(ToolExecution).where(ToolExecution.run_id == run_id))
            assert run.status == "COMPLETED"
            if approve:
                assert execution.status == "COMPLETED"
                assert execution.attempt == 1
            else:
                assert execution is None
            assert (await db.get(Approval, approval_id)).status == (
                "APPROVED" if approve else "REJECTED"
            )
    finally:
        if tool_id:
            async with factory() as db:
                saved_tool = await db.get(ToolDefinition, tool_id)
                saved_tool.policy = old_policy
                await db.commit()
        if run_id:
            await redis.delete(
                queue.stream,
                f"run:{run_id}:enqueued",
                EventStore.key(run_id),
                EventStore.sequence_key(run_id),
            )
        await redis.aclose()
        await engine.dispose()


async def test_waiting_run_cancel_closes_pending_approval():
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().hex[:8]
    try:
        async with factory() as db:
            model = ModelConfig(name=f"cancel-model-{suffix}", provider="openai", model_name="fake")
            db.add(model)
            await db.flush()
            agent = AgentDefinition(name=f"cancel-agent-{suffix}", model_id=model.id)
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="cancel-user")
            db.add(session)
            await db.flush()
            message = Message(
                session_id=session.id, user_id="cancel-user", role="user", content="hi"
            )
            db.add(message)
            await db.flush()
            run = Run(session_id=session.id, message_id=message.id, status="WAITING")
            db.add(run)
            await db.flush()
            approval = Approval(
                run_id=run.id,
                tool_call_id="cancel-call",
                tool_name="echo",
                title="确认",
                description="",
                risk="LOW",
                status="PENDING",
            )
            db.add(approval)
            await db.commit()

        async with factory() as db:
            assert await ApprovalRepository(db).cancel_waiting(run.id)
            assert (await db.get(Run, run.id)).status == "CANCELLED"
            assert (await db.get(Approval, approval.id)).status == "CANCELLED"
    finally:
        await engine.dispose()
