import os

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.runtime.agent import LangChainAgentRuntime


async def test_runtime_persists_langgraph_checkpoint():
    async with AsyncPostgresSaver.from_conn_string(
        os.environ["TEST_CHECKPOINT_DATABASE_URL"]
    ) as saver:
        await saver.setup()
        runtime = LangChainAgentRuntime(
            model=FakeMessagesListChatModel(responses=[AIMessage(content="完成")]),
            tools=[],
            system_prompt="测试",
            max_steps=5,
            checkpointer=saver,
        )

        async def emit(_kind, _data):
            pass

        async def not_cancelled():
            return False

        answer = await runtime.run(
            "checkpoint-test-1", [HumanMessage(content="你好")], emit, not_cancelled
        )
        assert answer == "完成"
        checkpoint = await saver.aget_tuple({"configurable": {"thread_id": "checkpoint-test-1"}})
        assert checkpoint is not None
