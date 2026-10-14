from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from datetime import datetime

from app.context.budget import ContextBudget
from app.context.errors import (
    ContextBudgetExceeded,
    ContextInputTooLarge,
    ContextSummaryFailed,
    RunContextMissing,
)
from app.context.summary import summarizer_prompt, summary_prompt_hash, summary_token_estimate
from app.context.tokens import approximate_tokens

SummaryModel = Callable[[str], Awaitable[str]]


@dataclass(frozen=True)
class ContextMessage:
    id: str
    role: str
    content: str
    created_at: datetime


@dataclass(frozen=True)
class SummaryView:
    id: str | None
    revision: int
    text: str
    token_estimate: int
    from_message_id: str
    through_message_id: str
    through_created_at: datetime
    source_message_count: int
    prompt_hash: str


@dataclass(frozen=True)
class NewSummary:
    from_message_id: str
    through_message_id: str
    summary: str
    token_estimate: int
    source_message_count: int
    prompt_hash: str


@dataclass(frozen=True)
class PlannedContext:
    summary_insert: NewSummary | None
    existing_summary_id: str | None
    summary_text: str | None
    message_ids: list[str]
    estimated_tokens: int
    expected_revision: int | None


@dataclass(frozen=True)
class _Ready:
    messages: list[ContextMessage]
    estimated_tokens: int


@dataclass(frozen=True)
class _Compact:
    batch: list[ContextMessage]
    prompt: str
    raw: list[ContextMessage]
    estimated_tokens: int
    over_hard: bool


@dataclass(frozen=True)
class _Fail:
    pass


def decide_context_action(*, snapshot: bool, checkpoint: bool, observed: bool) -> str:
    if snapshot:
        return "snapshot"
    if checkpoint:
        return "checkpoint"
    if observed:
        return "missing"
    return "plan"


def _current(messages: list[ContextMessage], current_message_id: str) -> ContextMessage:
    for message in messages:
        if message.id == current_message_id:
            return message
    raise RunContextMissing("当前用户消息不在可规划的对话范围内")


def _covered(summary: SummaryView, message: ContextMessage) -> bool:
    return (message.created_at, message.id) <= (
        summary.through_created_at,
        summary.through_message_id,
    )


def _history(
    summary: SummaryView | None, messages: list[ContextMessage], current: ContextMessage
) -> list[ContextMessage]:
    return [
        message
        for message in messages
        if message.id != current.id and not (summary is not None and _covered(summary, message))
    ]


def _split(
    history: list[ContextMessage], room: int
) -> tuple[list[ContextMessage], list[ContextMessage]]:
    tail_reversed: list[ContextMessage] = []
    used = 0
    for message in reversed(history):
        cost = approximate_tokens(message.content)
        if used + cost > room:
            break
        tail_reversed.append(message)
        used += cost
    tail = list(reversed(tail_reversed))
    return history[: len(history) - len(tail)], tail


def _evaluate(
    summary: SummaryView | None,
    messages: list[ContextMessage],
    current_message_id: str,
    budget: ContextBudget,
) -> _Ready | _Compact | _Fail:
    current = _current(messages, current_message_id)
    current_tokens = approximate_tokens(current.content)
    if current_tokens > budget.conversation_input_budget or current_tokens > budget.hard_limit:
        raise ContextInputTooLarge("当前用户消息超过模型输入预算")
    history = _history(summary, messages, current)
    summary_tokens = summary.token_estimate if summary is not None else 0
    raw = history + [current]
    estimated = summary_tokens + sum(approximate_tokens(message.content) for message in raw)
    if estimated <= budget.soft_limit:
        return _Ready(raw, estimated)
    room = budget.soft_limit - current_tokens - summary_tokens
    batch, _tail = _split(history, max(room, 0))
    if not batch:
        if estimated > budget.hard_limit:
            return _Fail()
        return _Ready(raw, estimated)
    return _Compact(
        batch,
        summarizer_prompt(summary.text if summary else None, batch),
        raw,
        estimated,
        estimated > budget.hard_limit,
    )


def _planned(
    original: SummaryView | None, summary: SummaryView | None, ready: _Ready
) -> PlannedContext:
    created = summary is not None and (original is None or summary.revision != original.revision)
    return PlannedContext(
        summary_insert=NewSummary(
            from_message_id=summary.from_message_id,
            through_message_id=summary.through_message_id,
            summary=summary.text,
            token_estimate=summary.token_estimate,
            source_message_count=summary.source_message_count,
            prompt_hash=summary.prompt_hash,
        )
        if created and summary is not None
        else None,
        existing_summary_id=None if created else (original.id if original else None),
        summary_text=summary.text if summary is not None else None,
        message_ids=[message.id for message in ready.messages],
        estimated_tokens=ready.estimated_tokens,
        expected_revision=original.revision if original is not None else None,
    )


async def plan_initial_context(
    *,
    summary: SummaryView | None,
    messages: list[ContextMessage],
    current_message_id: str,
    budget: ContextBudget,
    summarize: SummaryModel,
) -> PlannedContext:
    """规划第一次模型调用前的上下文。摘要调用由传入函数完成，不进入 Agent 循环。"""
    original = summary
    rounds = 0
    while True:
        decision = _evaluate(summary, messages, current_message_id, budget)
        if isinstance(decision, _Ready):
            return _planned(original, summary, decision)
        if isinstance(decision, _Fail):
            raise ContextBudgetExceeded("对话上下文超过预算，压缩后仍无法放入模型")
        if rounds >= budget.max_compaction_rounds:
            if decision.over_hard:
                raise ContextBudgetExceeded("对话上下文超过预算，压缩后仍无法放入模型")
            return _planned(original, summary, _Ready(decision.raw, decision.estimated_tokens))
        rounds += 1
        summary = await _summarize_batch(
            summary, decision.batch, summarize, budget.summary_input_budget
        )


def _chunk_for_summary(
    previous: str | None, messages: list[ContextMessage], limit: int
) -> list[ContextMessage]:
    """取最长的前缀，使摘要提示词不超过摘要模型的输入预算。"""
    chosen: list[ContextMessage] = []
    for message in messages:
        prompt = summarizer_prompt(previous, chosen + [message])
        if approximate_tokens(prompt) > limit:
            break
        chosen.append(message)
    return chosen


async def _summarize_batch(
    summary: SummaryView | None,
    batch: list[ContextMessage],
    summarize: SummaryModel,
    summary_input_budget: int,
) -> SummaryView:
    """一次压缩内按摘要模型的输入预算分批调用，只产生一份新摘要。"""
    if summary_input_budget <= 0:
        raise ContextBudgetExceeded("摘要模型没有可用的输入预算")
    previous = summary.text if summary is not None else None
    remaining = list(batch)
    text = ""
    last_prompt = ""
    while remaining:
        chunk = _chunk_for_summary(previous, remaining, summary_input_budget)
        if not chunk:
            raise ContextBudgetExceeded("待压缩的历史超过摘要模型的输入预算，无法继续分批")
        last_prompt = summarizer_prompt(previous, chunk)
        try:
            text = str(await summarize(last_prompt)).strip()
        except ContextSummaryFailed:
            raise
        except Exception as exc:
            raise ContextSummaryFailed("上下文摘要失败") from exc
        if not text:
            raise ContextSummaryFailed("上下文摘要失败")
        previous = text
        remaining = remaining[len(chunk) :]
    return SummaryView(
        id=None,
        revision=(summary.revision + 1) if summary is not None else 1,
        text=text,
        token_estimate=summary_token_estimate(text),
        from_message_id=summary.from_message_id if summary is not None else batch[0].id,
        through_message_id=batch[-1].id,
        through_created_at=batch[-1].created_at,
        source_message_count=(summary.source_message_count if summary else 0) + len(batch),
        prompt_hash=summary_prompt_hash(last_prompt),
    )
