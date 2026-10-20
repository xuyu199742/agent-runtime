"""在 Agent 模型调用前压缩可恢复的 Working Context。"""

import hashlib
import json
from collections.abc import Awaitable, Callable

from langchain.agents.middleware import AgentMiddleware
from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    RemoveMessage,
    ToolMessage,
)
from langgraph.config import get_config
from langgraph.graph.message import REMOVE_ALL_MESSAGES

from app.context.errors import ContextBudgetExceeded, ContextStateMismatch, ContextSummaryFailed
from app.context.tokens import approximate_tokens
from app.context.working import ToolFactRef, WorkingMessage, complete_groups, plan_working_context

FactLoader = Callable[[], Awaitable[dict[str, ToolFactRef]]]
SUMMARY_FIELDS = {"goal", "facts", "decisions", "completed", "pending", "references", "next_step"}


def _working_messages(messages: list[BaseMessage]) -> tuple[WorkingMessage, ...]:
    result = []
    for message in messages:
        if not isinstance(message.content, str) or not message.id:
            raise ContextBudgetExceeded("Working Context 包含无法安全压缩的消息")
        role = {"human": "user", "ai": "assistant", "tool": "tool", "system": "system"}.get(
            message.type
        )
        if role is None:
            raise ContextBudgetExceeded("Working Context 包含不支持的消息类型")
        calls = message.tool_calls if isinstance(message, AIMessage) else []
        result.append(
            WorkingMessage(
                id=message.id,
                role=role,
                content=message.content,
                tool_call_ids=tuple(str(call["id"]) for call in calls),
                tool_call_id=message.tool_call_id if isinstance(message, ToolMessage) else None,
                tool_call_payload=json.dumps(
                    calls, ensure_ascii=False, sort_keys=True, default=str
                ),
            )
        )
    return tuple(result)


def _summary_prompt(source: tuple[WorkingMessage, ...], refs: dict[str, ToolFactRef]) -> str:
    content = [
        {
            "role": message.role,
            "content": message.content,
            "tool_call_ids": message.tool_call_ids,
            "tool_call_id": message.tool_call_id,
            "tool_call_payload": message.tool_call_payload,
            "fact_reference": (
                {
                    "tool_execution_id": refs[message.tool_call_id].execution_id,
                    "result_hash": refs[message.tool_call_id].result_hash,
                    "artifact_id": refs[message.tool_call_id].artifact_id,
                }
                if message.role == "tool" and message.tool_call_id in refs
                else None
            ),
        }
        for message in source
    ]
    return (
        "请压缩以下已完成的历史交互。只返回 JSON 对象，包含 goal、facts、decisions、"
        "completed、pending、references、next_step 七个字段。不得把推测写成已验证事实；"
        "事实必须附可定位的工具执行引用。保留未完成事项、约束和下一步。\n"
        + json.dumps(content, ensure_ascii=False, sort_keys=True)
    )


def _source_refs(source: tuple[WorkingMessage, ...], refs: dict[str, ToolFactRef]) -> set[str]:
    allowed = {
        refs[message.tool_call_id].execution_id
        for message in source
        if message.role == "tool" and message.tool_call_id in refs
    }
    for message in source:
        if (
            message.role != "assistant"
            or not message.id.startswith("working-")
            or not message.content.startswith("[Run 内历史摘要]\n")
        ):
            continue
        try:
            previous = json.loads(message.content.split("\n", 1)[1])
        except ValueError as exc:
            raise ContextStateMismatch("Working Context 历史摘要格式无效") from exc
        if not isinstance(previous, dict) or not isinstance(previous.get("references"), list):
            raise ContextStateMismatch("Working Context 历史摘要引用无效")
        if not all(isinstance(ref, str) for ref in previous["references"]):
            raise ContextStateMismatch("Working Context 历史摘要引用无效")
        allowed.update(previous["references"])
    return allowed


def _validated_summary(content: str, *, allowed_refs: set[str]) -> str:
    try:
        parsed = json.loads(content)
    except (TypeError, ValueError) as exc:
        raise ContextSummaryFailed("Working Context 摘要格式无效") from exc
    if not isinstance(parsed, dict) or set(parsed) != SUMMARY_FIELDS:
        raise ContextSummaryFailed("Working Context 摘要字段无效")
    if not all(isinstance(parsed[key], str) for key in ("goal", "next_step")):
        raise ContextSummaryFailed("Working Context 摘要字段无效")
    if not all(
        isinstance(parsed[key], list) and all(isinstance(item, str) for item in parsed[key])
        for key in ("facts", "decisions", "completed", "pending", "references")
    ):
        raise ContextSummaryFailed("Working Context 摘要字段无效")
    if not set(parsed["references"]).issubset(allowed_refs):
        raise ContextSummaryFailed("Working Context 摘要包含未知事实引用")
    if parsed["facts"] and not parsed["references"]:
        raise ContextSummaryFailed("Working Context 已验证事实缺少引用")
    return json.dumps(parsed, ensure_ascii=False, sort_keys=True)


class WorkingContextMiddleware(AgentMiddleware):
    def __init__(
        self,
        *,
        model,
        journal,
        soft_limit: int,
        hard_limit: int,
        summary_input_budget: int,
        max_compaction_rounds: int,
        fact_refs_loader: FactLoader,
        recent_complete_turns: int = 1,
    ) -> None:
        self.model = model
        self.journal = journal
        self.soft_limit = soft_limit
        self.hard_limit = hard_limit
        self.summary_input_budget = summary_input_budget
        self.max_compaction_rounds = max_compaction_rounds
        self.fact_refs_loader = fact_refs_loader
        self.recent_complete_turns = recent_complete_turns

    async def _summarize(
        self,
        source_hash: str,
        source: tuple[WorkingMessage, ...],
        refs: dict[str, ToolFactRef],
    ) -> str:
        metadata = get_config().get("metadata") or {}
        graph_step = metadata.get("langgraph_step")
        if graph_step is None:
            raise ContextSummaryFailed("Working Context 缺少 Graph Step")
        round_id = f"{self.journal.run_id}:working:{graph_step}:{source_hash}"
        groups = list(complete_groups(source))
        previous_summary: WorkingMessage | None = None
        batch = 0
        while groups:
            prefix = (previous_summary,) if previous_summary is not None else ()
            selected: list[tuple[WorkingMessage, ...]] = []
            for group in groups:
                candidate = prefix + tuple(
                    message for part in (*selected, group) for message in part
                )
                if approximate_tokens(_summary_prompt(candidate, refs)) > self.summary_input_budget:
                    break
                selected.append(group)
            if not selected:
                raise ContextBudgetExceeded("Working Context 单个完整交互组超过摘要输入预算")
            chunk = prefix + tuple(message for part in selected for message in part)
            step_id = (
                round_id
                if batch == 0 and len(selected) == len(groups)
                else f"{round_id}:part:{batch}"
            )
            await self.journal.ensure_working_batch(step_id, graph_step, self.max_compaction_rounds)
            summary = await self._summarize_batch(
                step_id, chunk, refs, allowed_refs=_source_refs(chunk, refs)
            )
            groups = groups[len(selected) :]
            previous_summary = WorkingMessage(
                id=f"working-{source_hash}-{batch}",
                role="assistant",
                content=f"[Run 内历史摘要]\n{summary}",
            )
            batch += 1
        return summary

    async def _summarize_batch(
        self,
        step_id: str,
        source: tuple[WorkingMessage, ...],
        refs: dict[str, ToolFactRef],
        *,
        allowed_refs: set[str],
    ) -> str:
        prompt = _summary_prompt(source, refs)
        input_messages = [HumanMessage(content=prompt)]
        previous = await self.journal.completed_summary(step_id, input_messages)
        if previous is not None:
            return _validated_summary(previous, allowed_refs=allowed_refs)
        execution_id = await self.journal.start(step_id, "CONTEXT_SUMMARY", input_messages)
        try:
            response = await self.model.ainvoke(input_messages)
        except Exception:
            await self.journal.fail(execution_id)
            raise
        await self.journal.complete(execution_id, response)
        if not isinstance(response.content, str):
            raise ContextSummaryFailed("Working Context 摘要格式无效")
        return _validated_summary(response.content, allowed_refs=allowed_refs)

    async def abefore_model(self, state, runtime):
        messages = list(state["messages"])
        working = _working_messages(messages)
        refs = await self.fact_refs_loader()
        for message in working:
            if message.role != "tool" or message.tool_call_id not in refs:
                continue
            ref = refs[message.tool_call_id]
            stored_reference = f"tool_execution_id={ref.execution_id} sha256={ref.result_hash}"
            if stored_reference in message.content and message.content.startswith(
                "[较早工具结果："
            ):
                continue
            if hashlib.sha256(message.content.encode()).hexdigest() != ref.result_hash:
                raise ContextStateMismatch("ToolMessage 与持久 ToolExecution 结果不一致")
        plan = plan_working_context(
            working,
            soft_limit=self.soft_limit,
            hard_limit=self.hard_limit,
            fact_refs=refs,
            recent_complete_turns=self.recent_complete_turns,
        )
        if plan.action == "FAIL":
            raise ContextBudgetExceeded("Working Context 超过模型输入预算")
        if plan.action == "KEEP":
            return None
        by_id = {message.id: message for message in plan.messages}
        replacement = [
            message.model_copy(update={"content": by_id[message.id].content})
            if message.content != by_id[message.id].content
            else message
            for message in messages
        ]
        if plan.action == "SUMMARIZE":
            if self.max_compaction_rounds < 1:
                raise ContextBudgetExceeded("Working Context 压缩轮数不足")
            summary = await self._summarize(plan.source_hash, plan.summary_source, refs)
            selected = set(plan.summarize_ids)
            first = next(
                index for index, message in enumerate(replacement) if message.id in selected
            )
            replacement = [message for message in replacement if message.id not in selected]
            replacement.insert(
                first,
                AIMessage(content=f"[Run 内历史摘要]\n{summary}", id=f"working-{plan.source_hash}"),
            )
        estimated = sum(
            approximate_tokens(message.content) + approximate_tokens(message.tool_call_payload) + 4
            for message in _working_messages(replacement)
        )
        if estimated > self.hard_limit:
            raise ContextBudgetExceeded("Working Context 压缩后仍超过模型输入预算")
        return {"messages": [RemoveMessage(id=REMOVE_ALL_MESSAGES), *replacement]}
