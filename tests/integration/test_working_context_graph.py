import os
from hashlib import sha256
from uuid import uuid4

from langchain_core.language_models.fake_chat_models import FakeMessagesListChatModel
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage
from langchain_core.tools import tool
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.context.working import ToolFactRef
from app.runtime.agent import LangChainAgentRuntime
from app.runtime.working_context import WorkingContextMiddleware


class _Journal:
    run_id = "working-run"

    async def completed_summary(self, step_id, messages):
        return None

    async def start(self, step_id, phase, messages):
        return "execution"

    async def complete(self, execution_id, message):
        pass

    async def fail(self, execution_id):
        pass


async def _refs():
    return {"old-call": ToolFactRef("execution-old", sha256(("长结果" * 60).encode()).hexdigest())}


async def test_graph_commits_working_context_before_agent_model():
    seen = []
    saved_before_model = []
    saver = InMemorySaver()

    class Model(FakeMessagesListChatModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(list(messages))
            checkpoint = await saver.aget_tuple({"configurable": {"thread_id": "working-run"}})
            saved_before_model.extend(checkpoint.checkpoint["channel_values"]["messages"])
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = Model(responses=[AIMessage(content="完成")])
    middleware = WorkingContextMiddleware(
        model=model,
        journal=_Journal(),
        soft_limit=170,
        hard_limit=230,
        summary_input_budget=1000,
        max_compaction_rounds=1,
        fact_refs_loader=_refs,
    )
    runtime = LangChainAgentRuntime(
        model=model,
        tools=[],
        system_prompt="",
        max_model_calls=3,
        checkpointer=saver,
        working_context_middleware=middleware,
    )

    async def emit(_kind, _data):
        pass

    async def should_cancel():
        return False

    answer = await runtime.run(
        "working-run",
        [
            HumanMessage(content="之前", id="old-user"),
            AIMessage(
                content="",
                tool_calls=[{"id": "old-call", "name": "echo", "args": {"text": "x"}}],
                id="old-ai",
            ),
            ToolMessage(content="长结果" * 60, tool_call_id="old-call", id="old-tool"),
            HumanMessage(content="中间问题", id="recent-user"),
            AIMessage(content="中间答复", id="recent-ai"),
            HumanMessage(content="现在", id="current-user"),
        ],
        emit,
        should_cancel,
    )
    assert answer == "完成"
    assert seen
    assert any("tool_execution_id=execution-old" in str(m.content) for m in seen[0])
    assert any("tool_execution_id=execution-old" in str(m.content) for m in saved_before_model)
    state = await runtime.graph.aget_state({"configurable": {"thread_id": "working-run"}})
    assert state.created_at is not None


async def test_postgres_checkpoint_contains_reference_before_model_request():
    run_id = f"working-postgres-{uuid4()}"
    observed = []
    async with AsyncPostgresSaver.from_conn_string(
        os.environ["TEST_CHECKPOINT_DATABASE_URL"]
    ) as saver:
        await saver.setup()

        class Model(FakeMessagesListChatModel):
            async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
                checkpoint = await saver.aget_tuple({"configurable": {"thread_id": run_id}})
                observed.extend(checkpoint.checkpoint["channel_values"]["messages"])
                return await super()._agenerate(
                    messages, stop=stop, run_manager=run_manager, **kwargs
                )

        model = Model(responses=[AIMessage(content="完成")])
        runtime = LangChainAgentRuntime(
            model=model,
            tools=[],
            system_prompt="",
            max_model_calls=3,
            checkpointer=saver,
            working_context_middleware=WorkingContextMiddleware(
                model=model,
                journal=_Journal(),
                soft_limit=170,
                hard_limit=230,
                summary_input_budget=1000,
                max_compaction_rounds=1,
                fact_refs_loader=_refs,
            ),
        )

        async def emit(_kind, _data):
            pass

        async def should_cancel():
            return False

        await runtime.run(
            run_id,
            [
                HumanMessage(content="之前", id="old-user"),
                AIMessage(
                    content="",
                    tool_calls=[{"id": "old-call", "name": "echo", "args": {"text": "x"}}],
                    id="old-ai",
                ),
                ToolMessage(content="长结果" * 60, tool_call_id="old-call", id="old-tool"),
                HumanMessage(content="中间问题", id="recent-user"),
                AIMessage(content="中间答复", id="recent-ai"),
                HumanMessage(content="现在", id="current-user"),
            ],
            emit,
            should_cancel,
        )
    assert any("tool_execution_id=execution-old" in str(message.content) for message in observed)


async def test_tool_loop_references_older_result_before_third_model_call():
    seen = []

    @tool
    def long_result(value: str) -> str:
        """返回较长的测试结果。"""
        return f"{value}:" + "结果" * 35

    class Model(FakeMessagesListChatModel):
        def bind_tools(self, tools, **kwargs):
            return self

        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            seen.append(list(messages))
            return await super()._agenerate(messages, stop=stop, run_manager=run_manager, **kwargs)

    model = Model(
        responses=[
            AIMessage(
                content="",
                tool_calls=[{"id": "call-1", "name": "long_result", "args": {"value": "一"}}],
            ),
            AIMessage(
                content="",
                tool_calls=[{"id": "call-2", "name": "long_result", "args": {"value": "二"}}],
            ),
            AIMessage(content="完成"),
        ]
    )

    async def facts():
        return {
            "call-1": ToolFactRef(
                "execution-1", sha256(("一:" + "结果" * 35).encode()).hexdigest()
            ),
            "call-2": ToolFactRef(
                "execution-2", sha256(("二:" + "结果" * 35).encode()).hexdigest()
            ),
        }

    runtime = LangChainAgentRuntime(
        model=model,
        tools=[long_result],
        system_prompt="",
        max_model_calls=5,
        checkpointer=InMemorySaver(),
        working_context_middleware=WorkingContextMiddleware(
            model=model,
            journal=_Journal(),
            soft_limit=270,
            hard_limit=400,
            summary_input_budget=1000,
            max_compaction_rounds=1,
            fact_refs_loader=facts,
        ),
    )

    async def emit(_kind, _data):
        pass

    async def should_cancel():
        return False

    assert (
        await runtime.run("loop-run", [HumanMessage(content="开始")], emit, should_cancel) == "完成"
    )
    assert len(seen) == 3
    assert any("tool_execution_id=execution-1" in str(message.content) for message in seen[2])
    assert any("二:" in str(message.content) for message in seen[2])


async def test_summary_result_is_reused_after_hook_crashes_before_checkpoint():
    class ReplayJournal(_Journal):
        def __init__(self):
            self.completed = {}
            self.last_step = None
            self.starts = 0

        async def completed_summary(self, step_id, messages):
            return self.completed.get(step_id)

        async def start(self, step_id, phase, messages):
            self.last_step = step_id
            self.starts += 1
            return "summary-execution"

        async def complete(self, execution_id, message):
            self.completed[self.last_step] = message.content

    class SummaryModel:
        def __init__(self):
            self.calls = 0

        async def ainvoke(self, messages):
            self.calls += 1
            return AIMessage(
                content='{"goal":"继续","facts":[],"decisions":[],"completed":[],"pending":[],"references":[],"next_step":"回答"}'
            )

    class CrashAfterSummary(WorkingContextMiddleware):
        crashed = False

        async def abefore_model(self, state, runtime):
            update = await super().abefore_model(state, runtime)
            if not self.crashed:
                self.crashed = True
                raise RuntimeError("checkpoint 前崩溃")
            return update

    journal = ReplayJournal()
    summary_model = SummaryModel()
    saver = InMemorySaver()
    runtime = LangChainAgentRuntime(
        model=FakeMessagesListChatModel(responses=[AIMessage(content="完成")]),
        tools=[],
        system_prompt="",
        max_model_calls=3,
        checkpointer=saver,
        working_context_middleware=CrashAfterSummary(
            model=summary_model,
            journal=journal,
            soft_limit=90,
            hard_limit=150,
            summary_input_budget=1000,
            max_compaction_rounds=1,
            fact_refs_loader=lambda: _no_refs(),
        ),
    )

    async def emit(_kind, _data):
        pass

    async def should_cancel():
        return False

    messages = [
        HumanMessage(content="旧目标" * 50),
        AIMessage(content="旧答复"),
        HumanMessage(content="中间问题"),
        AIMessage(content="中间答复"),
        HumanMessage(content="当前问题"),
    ]
    import pytest

    with pytest.raises(RuntimeError, match="checkpoint 前崩溃"):
        await runtime.run("working-run", messages, emit, should_cancel)
    assert await runtime.run("working-run", messages, emit, should_cancel, resume=True) == "完成"
    assert summary_model.calls == 1
    assert journal.starts == 1


async def _no_refs():
    return {}
