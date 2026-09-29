import pytest
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage

from app.runtime.agent import LangChainAgentRuntime
from app.runtime.tools import calculator_tool


class ToolCallingFakeModel(FakeMessagesListChatModel):
    def bind_tools(self, tools, **kwargs):
        return self


class FailingModel(FakeMessagesListChatModel):
    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
        raise RuntimeError("模型暂不可用")


async def test_agent_calls_calculator_and_returns_answer():
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "calculator", "args": {"expression": "2+2"}, "id": "call-1"}],
            ),
            AIMessage(content="结果是 4"),
        ]
    )
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    async def not_cancelled():
        return False

    runtime = LangChainAgentRuntime(
        model=model, tools=[calculator_tool()], system_prompt="简洁回答", max_model_calls=5
    )
    answer = await runtime.run(
        run_id="run-1",
        messages=[HumanMessage(content="2+2 等于多少？")],
        emit=emit,
        should_cancel=not_cancelled,
    )
    assert answer == "结果是 4"
    assert any(kind == "tool.started" for kind, _ in events)
    assert any(kind == "tool.completed" for kind, _ in events)


async def test_agent_answers_without_tool():
    model = FakeMessagesListChatModel(responses=[AIMessage(content="你好")])

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    runtime = LangChainAgentRuntime(
        model=model, tools=[], system_prompt="简洁回答", max_model_calls=5
    )
    answer = await runtime.run("run-2", [HumanMessage(content="你好")], emit, not_cancelled)
    assert answer == "你好"


async def test_tool_failure_is_reported_without_crashing_agent():
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"name": "calculator", "args": {"expression": "1/0"}, "id": "call-2"}],
            ),
            AIMessage(content="无法计算"),
        ]
    )
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    async def not_cancelled():
        return False

    runtime = LangChainAgentRuntime(
        model=model, tools=[calculator_tool()], system_prompt="", max_model_calls=5
    )
    answer = await runtime.run("run-3", [HumanMessage(content="1/0")], emit, not_cancelled)
    assert answer == "无法计算"
    assert any(kind == "tool.failed" for kind, _ in events)


async def test_agent_stops_after_max_model_calls():
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "calculator", "args": {"expression": "1+1"}, "id": "call-loop"}
                ],
            )
        ]
    )

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    runtime = LangChainAgentRuntime(
        model=model, tools=[calculator_tool()], system_prompt="", max_model_calls=2
    )
    with pytest.raises(ModelCallLimitExceededError):
        await runtime.run("run-loop", [HumanMessage(content="一直计算")], emit, not_cancelled)


async def test_model_failure_propagates_to_run_boundary():
    runtime = LangChainAgentRuntime(
        model=FailingModel(responses=[AIMessage(content="unused")]),
        tools=[],
        system_prompt="",
        max_model_calls=2,
    )

    async def emit(_kind, _data):
        pass

    async def not_cancelled():
        return False

    with pytest.raises(RuntimeError, match="模型暂不可用"):
        await runtime.run("failed-model", [HumanMessage(content="你好")], emit, not_cancelled)


async def test_agent_handles_multiple_tool_calls_in_one_turn():
    model = ToolCallingFakeModel(
        responses=[
            AIMessage(
                content="",
                tool_calls=[
                    {"name": "calculator", "args": {"expression": "1+1"}, "id": "call-a"},
                    {"name": "calculator", "args": {"expression": "2+2"}, "id": "call-b"},
                ],
            ),
            AIMessage(content="分别是 2 和 4"),
        ]
    )
    events = []

    async def emit(kind, data):
        events.append((kind, data))

    async def not_cancelled():
        return False

    runtime = LangChainAgentRuntime(
        model=model, tools=[calculator_tool()], system_prompt="", max_model_calls=5
    )
    answer = await runtime.run(
        "multi-tool", [HumanMessage(content="分别计算")], emit, not_cancelled
    )
    assert answer == "分别是 2 和 4"
    assert [kind for kind, _ in events].count("tool.started") == 2
    assert [kind for kind, _ in events].count("tool.completed") == 2
