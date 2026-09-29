"""中途断流后的事件可由 logical step 重建，不拼接旧 partial。"""

import os
from uuid import uuid4

import pytest
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, AIMessageChunk, HumanMessage
from langchain_core.outputs import ChatGenerationChunk
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.runtime.agent import LangChainAgentRuntime, RunCancelled


class RestartingModel(FakeMessagesListChatModel):
    calls: int = 0

    async def _astream(self, messages, stop=None, run_manager=None, **kwargs):
        self.calls += 1
        parts = ["旧", "内容"] if self.calls == 1 else ["新", "答案"]
        for part in parts:
            yield ChatGenerationChunk(message=AIMessageChunk(content=part))


async def test_mid_model_stream_resume_replaces_partial_output():
    run_id = f"midstream-{uuid4()}"
    model = RestartingModel(responses=[AIMessage(content="unused")])
    events = []
    interrupted = False

    async def emit(kind, data):
        nonlocal interrupted
        events.append((kind, data))
        if kind == "model.delta" and model.calls == 1:
            interrupted = True

    async def should_cancel():
        return interrupted

    async with AsyncPostgresSaver.from_conn_string(
        os.environ["TEST_CHECKPOINT_DATABASE_URL"]
    ) as saver:
        await saver.setup()
        runtime = LangChainAgentRuntime(model, [], "", 5, saver)
        with pytest.raises(RunCancelled):
            await runtime.run(run_id, [HumanMessage(content="回答")], emit, should_cancel)
        interrupted = False
        answer = await runtime.run(
            run_id, [HumanMessage(content="回答")], emit, should_cancel, resume=True
        )

    assert answer == "新答案"
    starts = [data["step_id"] for kind, data in events if kind == "model.started"]
    assert len(starts) == 2
    assert starts[0] == starts[1]
    partial = {}
    for kind, data in events:
        if kind == "model.started":
            partial[data["step_id"]] = ""
        elif kind == "model.delta":
            partial[data["step_id"]] += data["text"]
        elif kind == "model.completed":
            assert data["step_id"] in partial
    assert partial[starts[0]] == "新答案"
