"""Run 内模型输入的纯规划逻辑；不修改持久执行事实。"""

import hashlib
import json
from dataclasses import dataclass, replace
from typing import Literal

from app.context.tokens import approximate_tokens


@dataclass(frozen=True)
class WorkingMessage:
    id: str
    role: str
    content: str
    tool_call_ids: tuple[str, ...] = ()
    tool_call_id: str | None = None


@dataclass(frozen=True)
class ToolFactRef:
    execution_id: str
    result_hash: str
    artifact_id: str | None = None


@dataclass(frozen=True)
class WorkingPlan:
    action: Literal["KEEP", "REFERENCE", "SUMMARIZE", "FAIL"]
    source_hash: str
    messages: tuple[WorkingMessage, ...]
    estimated_tokens: int
    summarize_ids: tuple[str, ...] = ()
    summary_source: tuple[WorkingMessage, ...] = ()


@dataclass(frozen=True)
class _Group:
    messages: tuple[WorkingMessage, ...]
    complete: bool


def _groups(messages: tuple[WorkingMessage, ...]) -> tuple[_Group, ...]:
    groups: list[_Group] = []
    index = 0
    while index < len(messages):
        message = messages[index]
        if message.role == "tool":
            raise ValueError("孤立 ToolMessage")
        if message.role != "assistant" or not message.tool_call_ids:
            groups.append(_Group((message,), True))
            index += 1
            continue
        expected = set(message.tool_call_ids)
        if len(expected) != len(message.tool_call_ids):
            raise ValueError("AI Tool Call ID 重复")
        collected = [message]
        seen: set[str] = set()
        index += 1
        while index < len(messages) and messages[index].role == "tool":
            result = messages[index]
            if result.tool_call_id not in expected or result.tool_call_id in seen:
                raise ValueError("ToolMessage 与 AI Tool Call 不匹配")
            seen.add(result.tool_call_id)
            collected.append(result)
            index += 1
        groups.append(_Group(tuple(collected), seen == expected))
    return tuple(groups)


def validate_tool_pairs(messages: tuple[WorkingMessage, ...]) -> bool:
    """允许正在执行的末尾 Tool batch，但不允许孤立或重复结果。"""
    _groups(messages)
    return True


def _estimate(messages: tuple[WorkingMessage, ...]) -> int:
    return sum(approximate_tokens(message.content) + 4 for message in messages)


def _source_hash(
    messages: tuple[WorkingMessage, ...],
    soft_limit: int,
    hard_limit: int,
    recent_complete_turns: int,
    fact_refs: dict[str, ToolFactRef],
) -> str:
    payload = {
        "messages": [
            {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "tool_call_ids": message.tool_call_ids,
                "tool_call_id": message.tool_call_id,
            }
            for message in messages
        ],
        "soft_limit": soft_limit,
        "hard_limit": hard_limit,
        "recent_complete_turns": recent_complete_turns,
        "fact_refs": {
            call_id: {
                "execution_id": ref.execution_id,
                "result_hash": ref.result_hash,
                "artifact_id": ref.artifact_id,
            }
            for call_id, ref in sorted(fact_refs.items())
        },
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _reference_content(ref: ToolFactRef) -> str:
    artifact = f" artifact_id={ref.artifact_id}" if ref.artifact_id else ""
    return (
        f"[较早工具结果：tool_execution_id={ref.execution_id} sha256={ref.result_hash}{artifact}]"
    )


def plan_working_context(
    messages: tuple[WorkingMessage, ...],
    *,
    soft_limit: int,
    hard_limit: int,
    fact_refs: dict[str, ToolFactRef] | None = None,
    recent_complete_turns: int = 1,
) -> WorkingPlan:
    if soft_limit < 0 or hard_limit < soft_limit or recent_complete_turns < 1:
        raise ValueError("Working Context 预算无效")
    refs = fact_refs or {}
    groups = _groups(messages)
    source_hash = _source_hash(messages, soft_limit, hard_limit, recent_complete_turns, refs)
    estimate = _estimate(messages)
    if any(not group.complete for group in groups):
        return WorkingPlan("FAIL", source_hash, messages, estimate)
    if estimate <= soft_limit:
        return WorkingPlan("KEEP", source_hash, messages, estimate)

    protected: set[str] = {message.id for message in messages if message.role == "system"}
    latest_user = next((message for message in reversed(messages) if message.role == "user"), None)
    if latest_user is not None:
        protected.add(latest_user.id)
    complete_kept = 0
    for group in reversed(groups):
        if not group.complete or complete_kept < recent_complete_turns:
            protected.update(message.id for message in group.messages)
        if group.complete:
            complete_kept += 1
    if _estimate(tuple(message for message in messages if message.id in protected)) > hard_limit:
        return WorkingPlan("FAIL", source_hash, messages, estimate)

    planned = list(messages)
    for index, message in enumerate(planned):
        if message.role != "tool" or message.id in protected:
            continue
        ref = refs.get(message.tool_call_id or "")
        if ref is None:
            continue
        replacement = _reference_content(ref)
        if approximate_tokens(replacement) < approximate_tokens(message.content):
            planned[index] = replace(message, content=replacement)
            if _estimate(tuple(planned)) <= soft_limit:
                return WorkingPlan(
                    "REFERENCE", source_hash, tuple(planned), _estimate(tuple(planned))
                )

    planned_messages = tuple(planned)
    estimate = _estimate(planned_messages)
    candidates = tuple(
        message
        for group in groups
        if group.complete and all(message.id not in protected for message in group.messages)
        for message in group.messages
    )
    if candidates:
        return WorkingPlan(
            "SUMMARIZE",
            source_hash,
            planned_messages,
            estimate,
            tuple(message.id for message in candidates),
            candidates,
        )
    if estimate > hard_limit:
        return WorkingPlan("FAIL", source_hash, planned_messages, estimate)
    action: Literal["KEEP", "REFERENCE"] = "REFERENCE" if planned_messages != messages else "KEEP"
    return WorkingPlan(action, source_hash, planned_messages, estimate)
