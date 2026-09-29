import os
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.messaging.events import EventStore
from app.messaging.run_queue import RunQueue
from app.persistence.database import (
    AgentDefinition,
    Message,
    ModelConfig,
    Run,
    Session,
    ToolDefinition,
)
from app.runtime.agent import LangChainAgentRuntime, RunCancelled
from app.runtime.checkpoint import create_checkpoint_pool, create_saver
from app.runtime.tools import calculator_tool
from app.worker import runner


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def test_crashed_worker_is_reclaimed_and_resumes_checkpoint(monkeypatch):
    engine = create_async_engine(os.environ["TEST_DATABASE_URL"])
    factory = async_sessionmaker(engine, expire_on_commit=False)
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    suffix = uuid4().hex[:8]
    queue = RunQueue(redis, stream=f"test:crash:{suffix}", group=f"test-crash-{suffix}")
    model = ToolModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "calculator", "args": {"expression": "2+2"}, "id": "crash-call"}
                ],
            ),
            AIMessage(content="答案是 4"),
        ]
    )
    try:
        async with factory() as db:
            model_config = ModelConfig(
                name=f"crash-model-{suffix}", provider="openai", model_name="fake"
            )
            tool = ToolDefinition(name=f"calculator-{suffix}", type="NATIVE", config={}, policy={})
            # Tool 的运行时名称应保持 calculator；独立测试库中复用现有定义。
            existing = await db.scalar(
                select(ToolDefinition).where(ToolDefinition.name == "calculator")
            )
            if existing is None:
                tool.name = "calculator"
                db.add(tool)
                existing = tool
            db.add(model_config)
            await db.flush()
            agent = AgentDefinition(name=f"crash-agent-{suffix}", model_id=model_config.id)
            agent.tools = [existing]
            db.add(agent)
            await db.flush()
            session = Session(agent_id=agent.id, user_id="user")
            db.add(session)
            await db.flush()
            message = Message(session_id=session.id, user_id="user", role="user", content="2+2")
            db.add(message)
            await db.flush()
            run = Run(
                session_id=session.id,
                message_id=message.id,
                status="RUNNING",
                lease_owner="worker-a",
                lease_until=datetime.now(UTC) - timedelta(seconds=1),
            )
            db.add(run)
            await db.commit()
            run_id = run.id

        pool = create_checkpoint_pool(os.environ["TEST_CHECKPOINT_DATABASE_URL"], concurrency=2)
        async with pool:
            saver = create_saver(pool)
            await saver.setup()
            cancel = False

            async def emit(kind, _data):
                nonlocal cancel
                if kind == "tool.completed":
                    cancel = True

            async def should_cancel():
                return cancel

            runtime = LangChainAgentRuntime(model, [calculator_tool()], "", 5, saver)
            with pytest.raises(RunCancelled):
                await runtime.run(run_id, [HumanMessage(content="2+2")], emit, should_cancel)

            await queue.ensure_group()
            await queue.enqueue(run_id)
            assert await queue.read("worker-a", block_ms=100)
            entry = (await queue.claim_idle("worker-b", min_idle_ms=0))[0]
            monkeypatch.setattr(runner, "session_factory", factory)
            monkeypatch.setattr(runner, "build_model", lambda _config: model)
            await runner.process_entry(
                entry[0], entry[1], "worker-b", redis, queue, EventStore(redis), create_saver(pool)
            )
            final_state = await runtime.graph.aget_state({"configurable": {"thread_id": run_id}})
            assert (
                sum(isinstance(item, HumanMessage) for item in final_state.values["messages"]) == 1
            )

        async with factory() as db:
            actual = await db.get(Run, run_id)
            assert actual.status == "COMPLETED"
            assert (await db.get(Message, actual.answer_message_id)).content == "答案是 4"
            assert (
                await db.scalar(
                    select(func.count(Message.id)).where(
                        Message.session_id == session.id, Message.role == "assistant"
                    )
                )
                == 1
            )
    finally:
        await redis.delete(queue.stream, f"run:{run_id}:enqueued")
        await redis.aclose()
        await engine.dispose()
