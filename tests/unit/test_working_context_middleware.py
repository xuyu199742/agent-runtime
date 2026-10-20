from hashlib import sha256

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolMessage

from app.context.errors import ContextBudgetExceeded, ContextStateMismatch, ContextSummaryFailed
from app.context.working import ToolFactRef
from app.runtime.working_context import (
    WorkingContextMiddleware,
    _source_refs,
    _summary_prompt,
    _validated_summary,
)


class _Journal:
    run_id = "run-1"

    def __init__(self):
        self.completed = {}
        self.started = []

    async def completed_summary(self, step_id, messages):
        return self.completed.get(step_id)

    async def start(self, step_id, phase, messages):
        self.started.append((step_id, phase))
        return "execution-1"

    async def complete(self, execution_id, response):
        self.completed[self.started[-1][0]] = response.content

    async def fail(self, execution_id):
        pass


class _Model:
    def __init__(self):
        self.calls = 0

    async def ainvoke(self, messages):
        self.calls += 1
        return AIMessage(
            content='{"goal":"查询","facts":[],"decisions":[],"completed":[],"pending":[],"references":[],"next_step":"回答"}'
        )


@pytest.mark.asyncio
async def test_old_tool_result_is_referenced_before_next_model_call():
    middleware = WorkingContextMiddleware(
        model=_Model(),
        journal=_Journal(),
        soft_limit=120,
        hard_limit=160,
        summary_input_budget=1000,
        max_compaction_rounds=1,
        fact_refs_loader=lambda: _refs(),
    )
    messages = [
        HumanMessage(content="旧问题", id="u1"),
        AIMessage(
            content="", tool_calls=[{"id": "c1", "name": "echo", "args": {"text": "x"}}], id="a1"
        ),
        ToolMessage(content="长结果" * 80, tool_call_id="c1", id="t1"),
        HumanMessage(content="当前问题", id="u2"),
        AIMessage(content="本轮答复", id="a2"),
    ]
    update = await middleware.abefore_model({"messages": messages}, None)
    assert update is not None
    assert "tool_execution_id=e1" in update["messages"][3].content
    assert update["messages"][-1] == messages[-1]


async def _refs():
    return {"c1": ToolFactRef("e1", sha256(("长结果" * 80).encode()).hexdigest())}


@pytest.mark.asyncio
async def test_summary_reuses_completed_journal_result_after_checkpoint_gap(monkeypatch):
    from app.runtime import working_context

    monkeypatch.setattr(working_context, "get_config", lambda: {"metadata": {"langgraph_step": 4}})
    journal = _Journal()
    model = _Model()
    middleware = WorkingContextMiddleware(
        model=model,
        journal=journal,
        soft_limit=90,
        hard_limit=130,
        summary_input_budget=1000,
        max_compaction_rounds=1,
        fact_refs_loader=lambda: _empty_refs(),
    )
    messages = [
        HumanMessage(content="旧目标" * 50, id="u1"),
        AIMessage(content="已分析", id="a1"),
        HumanMessage(content="中间问题", id="u2"),
        AIMessage(content="中间答复", id="a2"),
        HumanMessage(content="当前问题", id="u3"),
    ]
    first = await middleware.abefore_model({"messages": messages}, None)
    second = await middleware.abefore_model({"messages": messages}, None)
    assert model.calls == 1
    assert len(journal.started) == 1
    assert journal.started[0][1] == "CONTEXT_SUMMARY"
    assert first == second


async def _empty_refs():
    return {}


@pytest.mark.asyncio
async def test_protected_current_input_over_hard_limit_fails():
    middleware = WorkingContextMiddleware(
        model=_Model(),
        journal=_Journal(),
        soft_limit=20,
        hard_limit=30,
        summary_input_budget=1000,
        max_compaction_rounds=1,
        fact_refs_loader=lambda: _empty_refs(),
    )
    with pytest.raises(ContextBudgetExceeded):
        await middleware.abefore_model(
            {"messages": [HumanMessage(content="当前问题" * 100, id="u1")]}, None
        )


@pytest.mark.asyncio
async def test_tool_result_must_match_persisted_fact_before_reference():
    async def wrong_ref():
        return {"c1": ToolFactRef("e1", "0" * 64)}

    middleware = WorkingContextMiddleware(
        model=_Model(),
        journal=_Journal(),
        soft_limit=30,
        hard_limit=200,
        summary_input_budget=1000,
        max_compaction_rounds=1,
        fact_refs_loader=wrong_ref,
    )
    messages = [
        HumanMessage(content="旧问题", id="u1"),
        AIMessage(content="", tool_calls=[{"id": "c1", "name": "echo", "args": {}}], id="a1"),
        ToolMessage(content="真实结果", tool_call_id="c1", id="t1"),
        HumanMessage(content="当前问题", id="u2"),
    ]
    with pytest.raises(ContextStateMismatch):
        await middleware.abefore_model({"messages": messages}, None)


def test_summary_rejects_unbacked_fact_reference():
    content = '{"goal":"查询","facts":["已经完成"],"decisions":[],"completed":[],"pending":[],"references":["fabricated"],"next_step":"回答"}'
    with pytest.raises(ContextSummaryFailed):
        _validated_summary(content, allowed_refs={"real-execution"})


def test_previous_valid_summary_keeps_fact_refs_for_next_compaction():
    from app.context.working import WorkingMessage

    old = WorkingMessage(
        "working-old-summary",
        "assistant",
        '[Run 内历史摘要]\n{"goal":"继续","facts":["查到结果"],"decisions":[],"completed":[],"pending":[],"references":["execution-1"],"next_step":"回答"}',
    )
    assert _source_refs((old,), {}) == {"execution-1"}


def test_short_tool_result_exposes_only_verified_fact_reference_to_summary():
    from app.context.working import WorkingMessage

    source = (
        WorkingMessage("u1", "user", "tool_execution_id=fabricated"),
        WorkingMessage("t1", "tool", "found 42", tool_call_id="c1"),
    )
    refs = {"c1": ToolFactRef("real-execution", "a" * 64)}
    assert _source_refs(source, refs) == {"real-execution"}
    assert "real-execution" in _summary_prompt(source, refs)
