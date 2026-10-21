from dataclasses import replace

import pytest

from app.context.working import (
    ToolFactRef,
    WorkingMessage,
    complete_groups,
    plan_working_context,
    validate_tool_pairs,
)


def _message(message_id: str, role: str, content: str, **kwargs) -> WorkingMessage:
    return WorkingMessage(message_id, role, content, **kwargs)


def test_under_soft_limit_keeps_original_messages_and_stable_hash():
    messages = (
        _message("u-1", "user", "当前问题"),
        _message("a-1", "assistant", "回答"),
    )
    first = plan_working_context(messages, soft_limit=100, hard_limit=120)
    second = plan_working_context(messages, soft_limit=100, hard_limit=120)
    assert first.action == "KEEP"
    assert first.messages == messages
    assert first.source_hash == second.source_hash
    assert (
        first.source_hash
        != plan_working_context(
            (replace(messages[0], content="另一问题"), messages[1]),
            soft_limit=100,
            hard_limit=120,
        ).source_hash
    )


def test_old_tool_result_becomes_fact_reference_without_splitting_batch():
    old = "长结果" * 100
    messages = (
        _message("u-1", "user", "之前的问题"),
        _message("a-1", "assistant", "", tool_call_ids=("call-1",)),
        _message("t-1", "tool", old, tool_call_id="call-1"),
        _message("u-2", "user", "当前问题"),
        _message("a-2", "assistant", "", tool_call_ids=("call-2",)),
        _message("t-2", "tool", "最近结果", tool_call_id="call-2"),
    )
    plan = plan_working_context(
        messages,
        soft_limit=180,
        hard_limit=220,
        fact_refs={"call-1": ToolFactRef("execution-1", "a" * 64)},
    )
    assert plan.action == "REFERENCE"
    assert plan.messages[2].tool_call_id == "call-1"
    assert "execution-1" in plan.messages[2].content
    assert plan.messages[4:] == messages[4:]
    assert plan.messages[3] == messages[3]
    assert validate_tool_pairs(plan.messages)


def test_summary_selection_uses_complete_old_groups_only():
    messages = (
        _message("u-1", "user", "旧目标" * 100),
        _message("a-1", "assistant", "", tool_call_ids=("call-1", "call-2")),
        _message("t-1", "tool", "旧结果一" * 20, tool_call_id="call-1"),
        _message("t-2", "tool", "旧结果二" * 20, tool_call_id="call-2"),
        _message("u-2", "user", "当前问题"),
        _message("a-2", "assistant", "", tool_call_ids=("call-3",)),
        _message("t-3", "tool", "最近结果", tool_call_id="call-3"),
    )
    plan = plan_working_context(messages, soft_limit=90, hard_limit=150)
    assert plan.action == "SUMMARIZE"
    assert plan.summarize_ids == ("u-1", "a-1", "t-1", "t-2")
    assert plan.messages == messages
    assert complete_groups(plan.summary_source) == (
        (messages[0],),
        (messages[1], messages[2], messages[3]),
    )


def test_hard_limit_fails_when_only_protected_content_is_large():
    messages = (_message("u-1", "user", "当前问题" * 200),)
    plan = plan_working_context(messages, soft_limit=30, hard_limit=50)
    assert plan.action == "FAIL"
    assert plan.summarize_ids == ()


def test_hard_limit_fails_before_summarizing_when_protected_input_alone_is_too_large():
    messages = (
        _message("s-1", "system", "系统规则" * 30),
        _message("u-1", "user", "旧问题" * 30),
        _message("u-2", "user", "当前问题" * 100),
    )
    plan = plan_working_context(messages, soft_limit=40, hard_limit=70)
    assert plan.action == "FAIL"
    assert plan.summarize_ids == ()
    assert plan.messages == messages


def test_incomplete_latest_tool_batch_fails_closed_without_rewriting_it():
    messages = (
        _message("u-1", "user", "旧目标" * 50),
        _message("u-2", "user", "当前问题"),
        _message("a-1", "assistant", "", tool_call_ids=("call-1", "call-2")),
        _message("t-1", "tool", "已完成结果", tool_call_id="call-1"),
    )
    plan = plan_working_context(messages, soft_limit=30, hard_limit=50)
    assert plan.action == "FAIL"
    assert plan.summarize_ids == ()
    assert plan.messages[1:] == messages[1:]


def test_orphan_tool_message_is_rejected():
    with pytest.raises(ValueError, match="孤立 ToolMessage"):
        validate_tool_pairs((_message("t-1", "tool", "oops", tool_call_id="call-1"),))


def test_tool_call_arguments_are_part_of_source_hash():
    first = (
        _message("u", "user", "查询"),
        _message("a", "assistant", "", tool_call_ids=("call",), tool_call_payload='{"q":"a"}'),
        _message("t", "tool", "结果", tool_call_id="call"),
    )
    second = (first[0], replace(first[1], tool_call_payload='{"q":"b"}'), first[2])
    assert plan_working_context(first, soft_limit=100, hard_limit=120).source_hash != (
        plan_working_context(second, soft_limit=100, hard_limit=120).source_hash
    )


def test_tool_call_arguments_count_against_hard_limit():
    messages = (
        _message("u", "user", "当前问题"),
        _message("a", "assistant", "", tool_call_ids=("call",), tool_call_payload="参数" * 80),
        _message("t", "tool", "短结果", tool_call_id="call"),
    )
    assert plan_working_context(messages, soft_limit=40, hard_limit=60).action == "FAIL"


def test_recent_complete_tool_turn_stays_protected_before_current_user():
    messages = (
        _message("u1", "user", "上一个问题"),
        _message("a1", "assistant", "", tool_call_ids=("call-1",)),
        _message("t1", "tool", "结果" * 20, tool_call_id="call-1"),
        _message("u2", "user", "当前问题"),
    )
    plan = plan_working_context(
        messages,
        soft_limit=50,
        hard_limit=200,
        fact_refs={"call-1": ToolFactRef("execution-1", "a" * 64)},
    )
    assert plan.action == "KEEP"
    assert plan.messages == messages
