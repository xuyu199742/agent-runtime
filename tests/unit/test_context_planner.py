from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest

from app.application.execution_spec import build_execution_spec
from app.context.budget import ContextBudget
from app.context.errors import (
    ContextBudgetExceeded,
    ContextInputTooLarge,
    ContextSummaryFailed,
)
from app.context.model_limits import fill_known_model_context
from app.context.planner import (
    ContextMessage,
    SummaryView,
    decide_context_action,
    plan_initial_context,
)
from app.context.snapshot import context_content_hash, render_context
from app.context.summary import summarizer_prompt
from app.context.tokens import approximate_tokens
from app.domain.agent import ToolDefinition
from app.domain.errors import ModelContextConfigMissing
from app.execution.config import redact_execution_snapshot, resolve_execution_config
from app.prompt.assembler import PLATFORM_IDENTITY, assemble
from app.worker.runner import classify_run_error


def _message(index: int, content: str, role: str = "user") -> ContextMessage:
    return ContextMessage(
        id=f"m{index:04d}",
        role=role,
        content=content,
        created_at=datetime(2026, 1, 1, tzinfo=UTC) + timedelta(seconds=index),
    )


def _budget(**overrides) -> ContextBudget:
    values = {
        "conversation_input_budget": 1000,
        "soft_limit": 750,
        "hard_limit": 900,
        "max_compaction_rounds": 2,
        "summary_input_budget": 100_000,
    }
    values.update(overrides)
    return ContextBudget(**values)


def test_context_action_prefers_snapshot_then_checkpoint():
    assert decide_context_action(snapshot=True, checkpoint=True, observed=True) == "snapshot"
    assert decide_context_action(snapshot=False, checkpoint=True, observed=True) == "checkpoint"
    assert decide_context_action(snapshot=False, checkpoint=False, observed=True) == "missing"
    assert decide_context_action(snapshot=False, checkpoint=False, observed=False) == "plan"


@pytest.mark.asyncio
async def test_long_conversation_summarizes_without_dropping_current_message():
    messages = [_message(index, "历史" * 40) for index in range(100)]
    messages.append(_message(100, "当前问题保持完整"))
    calls = []

    async def summarize(prompt: str) -> str:
        calls.append(prompt)
        return "压缩后的历史"

    planned = await plan_initial_context(
        summary=None,
        messages=messages,
        current_message_id="m0100",
        budget=_budget(
            conversation_input_budget=4000,
            soft_limit=2000,
            hard_limit=3000,
        ),
        summarize=summarize,
    )
    assert calls
    assert planned.summary_insert is not None
    assert planned.summary_insert.source_message_count > 0
    assert "m0000" not in planned.message_ids
    assert planned.message_ids[-1] == "m0100"
    assert "历史" * 40 not in planned.summary_insert.summary
    rendered = render_context(planned.summary_text, [messages[-1]])
    assert rendered[-1] == ("user", "当前问题保持完整")


@pytest.mark.asyncio
async def test_covered_messages_are_not_repeated_after_summary():
    summary = SummaryView(
        id="s1",
        revision=3,
        text="已有摘要",
        token_estimate=10,
        from_message_id="m0000",
        through_message_id="m0005",
        through_created_at=_message(5, "x").created_at,
        source_message_count=6,
        prompt_hash="abc",
    )
    messages = [_message(index, f"消息{index}") for index in range(6, 10)]
    messages.append(_message(10, "当前"))

    async def summarize(_prompt: str) -> str:
        raise AssertionError("预算内不应摘要")

    planned = await plan_initial_context(
        summary=summary,
        messages=messages,
        current_message_id="m0010",
        budget=_budget(),
        summarize=summarize,
    )
    assert planned.summary_insert is None
    assert planned.existing_summary_id == "s1"
    assert planned.message_ids == [f"m{index:04d}" for index in range(6, 11)]


@pytest.mark.asyncio
async def test_current_message_over_budget_is_rejected():
    with pytest.raises(ContextInputTooLarge):
        await plan_initial_context(
            summary=None,
            messages=[_message(1, "超" * 1000)],
            current_message_id="m0001",
            budget=_budget(conversation_input_budget=100, soft_limit=75, hard_limit=90),
            summarize=_unused_summary,
        )


@pytest.mark.asyncio
async def test_compaction_stops_after_max_rounds():
    async def summarize(_prompt: str) -> str:
        return "仍然很长" * 500

    with pytest.raises(ContextBudgetExceeded):
        await plan_initial_context(
            summary=None,
            messages=[_message(index, "历史" * 30) for index in range(10)] + [_message(10, "当前")],
            current_message_id="m0010",
            budget=_budget(
                conversation_input_budget=5000,
                soft_limit=200,
                hard_limit=400,
                max_compaction_rounds=2,
            ),
            summarize=summarize,
        )


@pytest.mark.asyncio
async def test_summary_failure_is_explicit():
    async def summarize(_prompt: str) -> str:
        raise RuntimeError("model down")

    with pytest.raises(ContextSummaryFailed):
        await plan_initial_context(
            summary=None,
            messages=[_message(index, "历史" * 40) for index in range(20)] + [_message(20, "当前")],
            current_message_id="m0020",
            budget=_budget(conversation_input_budget=4000, soft_limit=300, hard_limit=500),
            summarize=summarize,
        )


def test_prompt_hash_is_stable_and_content_is_frozen():
    first = assemble(instruction="维修助手", revision=4, environment="runtime_version=0.3")
    second = assemble(instruction="维修助手", revision=4, environment="runtime_version=0.3")
    changed = assemble(
        instruction="维修助手",
        revision=4,
        environment="runtime_version=0.3",
        identity="另一份平台身份",
    )
    assert first.hash == second.hash
    assert first.hash != changed.hash
    assert [section.name for section in first.sections] == [
        "platform_identity",
        "agent_instruction",
        "runtime_policy",
        "environment",
    ]
    assert first.sections[0].content == PLATFORM_IDENTITY
    assert first.sections[0].content != changed.sections[0].content
    assert first.hash != __import__("hashlib").sha256(first.rendered.encode()).hexdigest()


def test_execution_spec_v2_freezes_prompt_budget_and_secret():
    agent = SimpleNamespace(
        id="agent-1",
        revision=4,
        system_prompt="只回答维修问题",
        max_model_calls=7,
        tools=[
            ToolDefinition(
                name="calculator",
                type="NATIVE",
                description="计算",
                config={"timeout_seconds": 5},
                policy={},
            )
        ],
    )
    small = _model(4096)
    large = _model(32768)
    missing = _model(None)
    draft = build_execution_spec(agent, small)
    larger = build_execution_spec(agent, large)
    assert draft.schema_version == 4
    assert draft.snapshot["prompt"]["sections"][1]["content"] == "只回答维修问题"
    assert draft.snapshot["model"]["api_key_encrypted"] == "ciphertext"
    assert draft.snapshot["context_budget"]["tool_schema_tokens"] > 0
    assert (
        draft.snapshot["context_budget"]["conversation_input_budget"]
        < larger.snapshot["context_budget"]["conversation_input_budget"]
    )
    public = redact_execution_snapshot(draft.snapshot)
    assert "api_key_encrypted" not in public["model"]
    assert "ciphertext" not in str(public)
    with pytest.raises(ModelContextConfigMissing):
        build_execution_spec(agent, missing)


def test_v1_spec_keeps_original_prompt_and_v2_does_not_reread_agent():
    v1 = resolve_execution_config(
        SimpleNamespace(
            schema_version=1,
            snapshot={
                "system_prompt": "旧提示词",
                "max_model_calls": 3,
                "model": {
                    "provider": "openai",
                    "model_name": "old",
                    "base_url": None,
                    "config": {},
                    "api_key_encrypted": "old-secret",
                },
                "tools": [],
                "context": {"max_messages": 30, "max_tokens": 12000},
            },
        ),
        None,
        None,
        None,
    )
    assert v1.schema_version == 1
    assert v1.system_prompt == "旧提示词"
    assert v1.v1_max_tokens == 12000
    v2_snapshot = build_execution_spec(
        SimpleNamespace(
            id="agent",
            revision=1,
            system_prompt="冻结指令",
            max_model_calls=4,
            tools=[],
        ),
        _model(8192),
    ).snapshot
    resolved = resolve_execution_config(
        SimpleNamespace(schema_version=2, snapshot=v2_snapshot),
        SimpleNamespace(system_prompt="后来改过的指令"),
        None,
        None,
    )
    assert "冻结指令" in resolved.system_prompt
    assert "后来改过的指令" not in resolved.system_prompt


def test_context_errors_map_to_stable_codes():
    assert classify_run_error(ContextInputTooLarge()) == "CONTEXT_INPUT_TOO_LARGE"
    assert classify_run_error(ContextBudgetExceeded()) == "CONTEXT_BUDGET_EXCEEDED"
    assert classify_run_error(ContextSummaryFailed()) == "CONTEXT_SUMMARY_FAILED"


@pytest.mark.asyncio
async def test_long_history_is_summarized_within_summary_budget():
    prompts: list[str] = []

    async def summarize(prompt: str) -> str:
        prompts.append(prompt)
        assert approximate_tokens(prompt) <= 500
        return "短摘要"

    history = [_message(index, "历史" * 40) for index in range(40)]
    planned = await plan_initial_context(
        summary=None,
        messages=[*history, _message(40, "当前问题")],
        current_message_id="m0040",
        budget=_budget(
            conversation_input_budget=20_000,
            soft_limit=50,
            hard_limit=800,
            summary_input_budget=500,
        ),
        summarize=summarize,
    )
    assert len(prompts) >= 2
    assert approximate_tokens(summarizer_prompt(None, history)) > 500
    assert planned.summary_insert is not None
    assert planned.summary_insert.through_message_id == "m0039"
    assert planned.summary_insert.source_message_count == 40
    assert planned.message_ids == ["m0040"]


@pytest.mark.asyncio
async def test_one_history_message_larger_than_summary_budget_fails():
    async def summarize(_prompt: str) -> str:
        raise AssertionError("单条历史放不进摘要预算时不应调用模型")

    with pytest.raises(ContextBudgetExceeded):
        await plan_initial_context(
            summary=None,
            messages=[_message(1, "历史" * 400), _message(2, "当前")],
            current_message_id="m0002",
            budget=_budget(
                conversation_input_budget=20_000,
                soft_limit=50,
                hard_limit=100,
                summary_input_budget=100,
            ),
            summarize=summarize,
        )


def test_snapshot_hash_covers_summary_and_message_text():
    budget = {"conversation_input_budget": 10}
    original = context_content_hash("summary-1", "摘要", [_message(1, "原文")], budget)
    assert original == context_content_hash("summary-1", "摘要", [_message(1, "原文")], budget)
    assert original != context_content_hash("summary-1", "摘要", [_message(1, "被改过")], budget)
    assert original != context_content_hash(
        "summary-1", "另一份摘要", [_message(1, "原文")], budget
    )


def test_known_model_context_is_filled_per_model():
    filled = fill_known_model_context({"timeout_seconds": 60, "max_retries": 1}, "deepseek-flash")
    assert filled == {
        "timeout_seconds": 60,
        "max_retries": 1,
        "context_window": 1_048_576,
        "max_output_tokens": 393_216,
    }
    assert fill_known_model_context({}, "bonsai2") is None
    assert fill_known_model_context({}, "fake") is None
    assert (
        fill_known_model_context(
            {"context_window": 1_048_576, "max_output_tokens": 393_216}, "deepseek-flash"
        )
        is None
    )
    assert fill_known_model_context({"context_window": 8192}, "deepseek-flash") is None
    partial = fill_known_model_context({"max_output_tokens": 4096}, "deepseek-v4-pro")
    assert partial["context_window"] == 1_048_576
    assert partial["max_output_tokens"] == 4096


async def _unused_summary(_prompt: str) -> str:
    raise AssertionError("不应调用摘要")


def _model(window: int | None):
    config = {} if window is None else {"context_window": window, "max_output_tokens": 1024}
    return SimpleNamespace(
        provider="openai",
        model_name="gpt-test",
        base_url=None,
        config=config,
        api_key_encrypted="ciphertext",
        enabled=True,
    )
