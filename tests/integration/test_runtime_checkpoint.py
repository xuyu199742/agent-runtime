import asyncio
import os
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.runtime.agent import LangChainAgentRuntime, RunCancelled
from app.runtime.checkpoint import create_checkpoint_pool, create_saver
from app.runtime.tools import calculator_tool


class ToolModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


async def test_runtime_persists_langgraph_checkpoint():
    run_id = f"checkpoint-{uuid4()}"
    async with AsyncPostgresSaver.from_conn_string(
        os.environ["TEST_CHECKPOINT_DATABASE_URL"]
    ) as saver:
        await saver.setup()
        runtime = LangChainAgentRuntime(
            model=FakeMessagesListChatModel(responses=[AIMessage(content="完成")]),
            tools=[],
            system_prompt="测试",
            max_model_calls=5,
            checkpointer=saver,
        )

        async def emit(_kind, _data):
            pass

        async def not_cancelled():
            return False

        answer = await runtime.run(run_id, [HumanMessage(content="你好")], emit, not_cancelled)
        assert answer == "完成"
        checkpoint = await saver.aget_tuple({"configurable": {"thread_id": run_id}})
        assert checkpoint is not None


async def test_interrupted_run_resumes_from_persisted_thread():
    run_id = f"resume-{uuid4()}"
    model = ToolModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "calculator", "args": {"expression": "2+2"}, "id": "resume-tool"}
                ],
            ),
            AIMessage(content="答案是 4"),
        ]
    )
    cancel = False

    async def emit(kind, _data):
        nonlocal cancel
        if kind == "tool.completed":
            cancel = True

    async def should_cancel():
        return cancel

    async def not_cancelled():
        return False

    async with AsyncPostgresSaver.from_conn_string(
        os.environ["TEST_CHECKPOINT_DATABASE_URL"]
    ) as saver:
        await saver.setup()
        runtime = LangChainAgentRuntime(model, [calculator_tool()], "", 5, saver)
        with pytest.raises(RunCancelled):
            await runtime.run(run_id, [HumanMessage(content="2+2")], emit, should_cancel)
        restarted = LangChainAgentRuntime(model, [calculator_tool()], "", 5, saver)
        answer = await restarted.run(
            run_id, [HumanMessage(content="2+2")], emit, not_cancelled, resume=True
        )
        assert answer == "答案是 4"


async def test_concurrent_runs_use_pooled_checkpointer_connections():
    run_ids = [f"pool-{uuid4()}" for _ in range(4)]
    pool = create_checkpoint_pool(os.environ["TEST_CHECKPOINT_DATABASE_URL"], concurrency=2)

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    async with pool:
        setup_saver = create_saver(pool)
        await setup_saver.setup()

        async def one(run_id: str):
            saver = create_saver(pool)
            runtime = LangChainAgentRuntime(
                model=FakeMessagesListChatModel(responses=[AIMessage(content=run_id)]),
                tools=[],
                system_prompt="",
                max_model_calls=5,
                checkpointer=saver,
            )
            answer = await runtime.run(run_id, [HumanMessage(content="hi")], emit, not_cancelled)
            assert answer == run_id
            assert await saver.aget_tuple({"configurable": {"thread_id": run_id}}) is not None

        await asyncio.gather(*(one(run_id) for run_id in run_ids))
