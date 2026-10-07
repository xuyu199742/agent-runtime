"""V2 Run 第一次进入模型前的上下文规划。恢复只读快照，不读最新会话。"""

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

from app.context.budget import ContextBudget
from app.context.errors import ContextLeaseLost, RunContextMissing
from app.context.planner import decide_context_action, plan_initial_context
from app.context.snapshot import render_context
from app.execution.config import ResolvedExecutionConfig
from app.persistence.database import Message, Run
from app.persistence.repositories.context import (
    ContextCommitLost,
    commit_planned_context,
    context_snapshot,
    execution_observed,
    latest_summary,
    load_snapshot_messages,
    messages_for_planning,
    summary_view,
)


async def prepare_v2_messages(
    run_id: str,
    worker_id: str | None,
    config: ResolvedExecutionConfig,
    saver,
    summarize,
    db_factory,
) -> tuple[list[BaseMessage], bool]:
    async with db_factory() as db:
        run = await db.get(Run, run_id)
        snapshot = await context_snapshot(db, run_id)
        observed = await execution_observed(db, run)
    if snapshot is not None:
        return await _render_saved(db_factory, run_id), False
    checkpoint = None
    if saver is not None:
        checkpoint = await saver.aget_tuple({"configurable": {"thread_id": run_id}})
    action = decide_context_action(
        snapshot=False, checkpoint=checkpoint is not None, observed=observed
    )
    if action == "checkpoint":
        return [], True
    if action == "missing":
        raise RunContextMissing("Run 已开始执行，但上下文快照和检查点都不存在")
    await _plan_and_store(db_factory, run_id, worker_id, config, summarize)
    return await _render_saved(db_factory, run_id), False


async def _plan_and_store(
    db_factory, run_id: str, worker_id: str | None, config: ResolvedExecutionConfig, summarize
):
    async with db_factory() as db:
        run = await db.get(Run, run_id)
        current = await db.get(Message, run.message_id)
        if current is None:
            raise RunContextMissing("当前用户消息不存在")
        current_id = current.id
        summary_row = await latest_summary(db, run.session_id)
        summary = await summary_view(db, summary_row) if summary_row is not None else None
        messages = await messages_for_planning(db, run.session_id, current, summary_row)
    numbers = config.context_budget or {}
    policy = config.context_policy or {}
    planned = await plan_initial_context(
        summary=summary,
        messages=messages,
        current_message_id=current_id,
        budget=ContextBudget(
            conversation_input_budget=numbers["conversation_input_budget"],
            soft_limit=numbers["soft_limit"],
            hard_limit=numbers["hard_limit"],
            max_compaction_rounds=policy["max_compaction_rounds"],
        ),
        summarize=summarize,
    )
    try:
        await commit_planned_context(
            db_factory,
            run_id,
            worker_id,
            planned,
            provider=config.provider,
            model_name=config.model_name,
            context_budget=numbers,
        )
    except ContextCommitLost as exc:
        raise ContextLeaseLost from exc


async def _render_saved(db_factory, run_id: str) -> list[BaseMessage]:
    async with db_factory() as db:
        snapshot = await context_snapshot(db, run_id)
        if snapshot is None:
            raise ContextLeaseLost
        try:
            summary_text, messages = await load_snapshot_messages(db, snapshot)
        except ValueError as exc:
            raise RunContextMissing("上下文快照引用的消息不存在") from exc
    turns = []
    for role, content in render_context(summary_text, messages):
        if role == "assistant":
            turns.append(AIMessage(content=content))
        else:
            turns.append(HumanMessage(content=content))
    return turns
