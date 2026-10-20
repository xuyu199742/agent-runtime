import asyncio

import httpx
import openai
import psycopg
import structlog
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langchain_core.messages import HumanMessage
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.context.errors import ContextLeaseLost, ContextRunError
from app.domain.agent import ModelDefinition
from app.domain.session import ConversationTurn
from app.execution.config import resolve_execution_config
from app.messaging.events import EventStore
from app.messaging.run_queue import RunQueue
from app.persistence.database import (
    AgentDefinition,
    EffectRecord,
    ExecutionSpec,
    ModelConfig,
    Run,
    Session,
    ToolExecution,
    session_factory,
)
from app.persistence.repositories.approvals import ApprovalRepository
from app.persistence.repositories.conversations import ConversationRepository
from app.persistence.repositories.effects import EffectStore
from app.persistence.repositories.runs import claim_run, end_run, extend_lease, finish_run, wait_run
from app.persistence.repositories.tool_executions import ToolExecutionStore
from app.persistence.repositories.traces import TRACE_TYPES, ExecutionRecorder
from app.runtime.agent import LangChainAgentRuntime, RunCancelled, RunWaiting
from app.runtime.budget import BudgetLimitExceeded, RunDeadlineExceeded, check_deadline
from app.runtime.checkpoint import create_run_saver
from app.runtime.context import build_context
from app.runtime.effects.ticket import TicketCreateProvider
from app.runtime.factory import build_model, resolve_model_config
from app.runtime.tools import ToolConfigurationError, build_tools
from app.runtime.working_context import WorkingContextMiddleware
from app.worker.context_planning import prepare_v2_messages
from app.worker.model_recording import ModelCallJournal
from app.worker.working_context import load_tool_fact_refs

log = structlog.get_logger()


def build_effect_providers(config, settings) -> dict:
    providers = {}
    for tool in config.tools:
        if tool.get("effect_type", "READ_ONLY") == "READ_ONLY":
            continue
        if config.schema_version not in {3, 4, 5} or tool.get("name") != "ticket.create":
            raise ToolConfigurationError("ExecutionSpec 未冻结受控写入 Contract")
        contract = (tool.get("config") or {}).get("effect_contract") or {}
        if (
            contract.get("operation_name") != "ticket.create"
            or contract.get("contract_version") != 1
            or not contract.get("provider_namespace")
            or (tool.get("policy") or {}).get("write_allowed") is not True
            or not settings.ticket_service_base_url
            or not settings.ticket_service_token
        ):
            raise ToolConfigurationError("ticket.create 缺少受控 Contract 或服务配置")
        providers["ticket.create"] = TicketCreateProvider(
            contract["provider_namespace"],
            settings.ticket_service_base_url,
            settings.ticket_service_token,
        )
    return providers


class CoordinationLost(Exception):
    """运行协调层暂不可用，保留 RUNNING 与未 ACK 消息供恢复。"""


def classify_run_error(exc: Exception) -> str:
    if isinstance(exc, ContextRunError):
        return exc.code
    if isinstance(exc, ModelCallLimitExceededError):
        return "BUDGET_MODEL_CALLS_EXCEEDED"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, openai.APITimeoutError)):
        return "TIMEOUT"
    if isinstance(exc, ToolConfigurationError):
        return "TOOL_ERROR"
    if isinstance(exc, (openai.APIError, httpx.HTTPError, ValueError)):
        return "MODEL_ERROR"
    if isinstance(exc, (RedisError, SQLAlchemyError, OSError)):
        return "INTERNAL_ERROR"
    return "INTERNAL_ERROR"


async def safe_publish(
    events: EventStore,
    run_id: str,
    kind: str,
    data: dict,
    *,
    worker_id: str | None = None,
    record: bool = True,
) -> None:
    if record and kind in TRACE_TYPES - {
        "run.completed",
        "run.failed",
        "run.cancelled",
        "run.waiting",
    }:
        async with session_factory() as db:
            if (
                worker_id is None
                or await ExecutionRecorder(db).append(run_id, kind, data, worker_id=worker_id)
                is None
            ):
                raise ContextLeaseLost
            await db.commit()
    try:
        await events.publish(run_id, kind, data)
    except RedisError:
        log.warning("事件投递失败", run_id=run_id, event_type=kind)


async def maintain_lease(
    run_id: str, worker_id: str, redis: Redis, task: asyncio.Task, interval: float = 2
) -> str:
    while not task.done():
        await asyncio.sleep(interval)
        if task.done():
            break
        try:
            if await redis.exists(f"run:{run_id}:cancel"):
                task.cancel()
                return "cancelled"
            async with session_factory() as db:
                if not await extend_lease(db, run_id, worker_id):
                    task.cancel()
                    return "lease_lost"
        except Exception:
            log.exception("Run 监督失败，停止旧执行", run_id=run_id)
            task.cancel()
            return "lease_lost"
    return "finished"


async def run_agent(
    run_id: str,
    resumed: bool,
    redis: Redis,
    events: EventStore,
    saver: AsyncPostgresSaver,
    worker_id: str | None = None,
) -> str:
    async with session_factory() as db:
        run = await db.get(Run, run_id)
        session = await db.get(Session, run.session_id)
        spec = await db.get(ExecutionSpec, run.execution_spec_id) if run.execution_spec_id else None
        if run.execution_spec_id and spec is None:
            raise ValueError("Run 配置快照不存在")
        agent = await db.get(AgentDefinition, session.agent_id) if spec is None else None
        model_config = await db.get(ModelConfig, agent.model_id) if agent is not None else None
        config = resolve_execution_config(spec, agent, model_config, get_settings())
        history = None
        if config.schema_version < 2:
            history = await ConversationRepository(db).recent_messages(
                session.id,
                run.created_at,
                config.v1_max_messages or get_settings().context_max_messages,
            )
        session_id = session.id
        user_id = session.user_id

    structlog.contextvars.clear_contextvars()
    log_context = {
        "request_id": run_id,
        "run_id": run_id,
        "session_id": session_id,
        "user_id": user_id,
    }
    if worker_id is not None:
        log_context["worker_id"] = worker_id
    structlog.contextvars.bind_contextvars(**log_context)

    chat_model = build_model(
        resolve_model_config(
            ModelDefinition(
                provider=config.provider,
                model_name=config.model_name,
                base_url=config.base_url,
                config=config.model_options,
                enabled=config.enabled,
            ),
            config.api_key_encrypted,
        )
    )

    journal = (
        ModelCallJournal(
            session_factory,
            run_id,
            worker_id,
            config.provider,
            config.model_name,
            config.execution_budget,
        )
        if worker_id is not None
        else None
    )
    summary_call_number = 0

    async def summarize(prompt: str) -> str:
        # 摘要是上下文基础设施，不进入 Agent，也不消耗 max_model_calls。
        nonlocal summary_call_number
        summary_call_number += 1
        message = HumanMessage(content=prompt)
        execution_id = (
            await journal.start(
                f"{run_id}:summary:{summary_call_number}", "CONTEXT_SUMMARY", [message]
            )
            if journal is not None
            else None
        )
        try:
            response = await chat_model.ainvoke([message])
        except Exception:
            if execution_id is not None:
                await journal.fail(execution_id)
            raise
        if execution_id is not None:
            await journal.complete(execution_id, response)
        content = response.content
        if isinstance(content, list):
            return "".join(
                part.get("text", "") if isinstance(part, dict) else str(part) for part in content
            )
        return str(content)

    if config.schema_version >= 2:
        messages, force_resume = await prepare_v2_messages(
            run_id, worker_id, config, saver, summarize, session_factory
        )
        resumed = resumed or force_resume
    else:
        messages = build_context(
            [ConversationTurn(role=item.role, content=item.content) for item in history],
            max_messages=config.v1_max_messages or get_settings().context_max_messages,
            max_tokens=config.v1_max_tokens or get_settings().context_max_tokens,
        )
    await safe_publish(
        events, run_id, "run.resumed" if resumed else "run.started", {}, worker_id=worker_id
    )
    runtime = LangChainAgentRuntime(
        model=chat_model,
        tools=build_tools(config.tool_definitions()),
        system_prompt=config.system_prompt,
        max_model_calls=config.max_model_calls,
        checkpointer=create_run_saver(saver.conn, run_id, worker_id)
        if worker_id and saver is not None
        else saver,
        tool_execution_store=ToolExecutionStore(
            session_factory, worker_id, config.execution_budget
        ),
        run_id=run_id,
        tool_policies={tool["name"]: tool for tool in config.tools},
        approval_session_factory=session_factory,
        model_call_journal=journal,
        worker_id=worker_id,
        effect_store=EffectStore(session_factory, config.execution_budget) if worker_id else None,
        effect_providers=build_effect_providers(config, get_settings()),
        working_context_middleware=WorkingContextMiddleware(
            model=chat_model,
            journal=journal,
            soft_limit=config.context_budget["soft_limit"],
            hard_limit=config.context_budget["hard_limit"],
            summary_input_budget=config.context_budget["summary_input_budget"],
            max_compaction_rounds=config.context_policy["max_compaction_rounds"],
            recent_complete_turns=config.working_context["recent_complete_turns"],
            fact_refs_loader=lambda: load_tool_fact_refs(session_factory, run_id),
        )
        if config.schema_version == 5 and journal is not None
        else None,
    )

    approval_decisions = None
    if config.execution_budget is not None:
        try:
            check_deadline(run.created_at, config.execution_budget.max_duration_seconds)
        except RunDeadlineExceeded:
            # 已发送的写入必须先核对结果；后续模型与新调用仍各自受截止时间限制。
            async with session_factory() as db:
                unresolved = await db.scalar(
                    select(EffectRecord.id)
                    .outerjoin(ToolExecution, ToolExecution.effect_id == EffectRecord.id)
                    .where(
                        or_(
                            EffectRecord.origin_run_id == run_id,
                            EffectRecord.dispatch_run_id == run_id,
                            ToolExecution.run_id == run_id,
                        ),
                        EffectRecord.status.in_(["DISPATCHED", "UNCERTAIN", "RECONCILING"]),
                    )
                    .limit(1)
                )
            if unresolved is None:
                raise
    if resumed:
        try:
            interrupts = await runtime.inspect_interrupts(
                run_id, require_checkpoint=run.waiting_at is not None
            )
        except psycopg.Error as exc:
            raise CoordinationLost from exc
        if interrupts:
            decisions = {}
            async with session_factory() as db:
                approvals = ApprovalRepository(db)
                for pending in interrupts:
                    approval = await approvals.get(pending.approval_id)
                    if approval is not None and approval.status in {"APPROVED", "REJECTED"}:
                        decisions[pending.id] = approval.status == "APPROVED"
            if len(decisions) == len(interrupts):
                approval_decisions = decisions

    async def emit(kind: str, data: dict) -> None:
        await safe_publish(
            events,
            run_id,
            kind,
            data,
            worker_id=worker_id,
            record=kind
            not in {
                "model.started",
                "model.completed",
                "tool.started",
                "tool.completed",
                "tool.failed",
            },
        )

    async def should_cancel() -> bool:
        try:
            return bool(await redis.exists(f"run:{run_id}:cancel"))
        except RedisError as exc:
            raise CoordinationLost from exc

    return await runtime.run(
        run_id,
        messages,
        emit,
        should_cancel,
        session_id=session_id,
        user_id=user_id,
        resume=resumed,
        approval_decisions=approval_decisions,
        require_checkpoint=run.waiting_at is not None,
    )


async def execute_run(
    run_id: str,
    worker_id: str,
    resumed: bool,
    redis: Redis,
    events: EventStore,
    saver: AsyncPostgresSaver,
    heartbeat_interval: float = 2,
) -> bool:
    async def attempt_agent() -> tuple[str, str | Exception | None]:
        try:
            return "completed", await run_agent(run_id, resumed, redis, events, saver, worker_id)
        except RunCancelled:
            return "cancelled", None
        except RunWaiting as waiting:
            return "waiting", waiting
        except (CoordinationLost, ContextLeaseLost, psycopg.Error) as exc:
            log.warning("Run 协调失效，等待租约恢复", run_id=run_id, error_type=type(exc).__name__)
            return "lease_lost", None
        except Exception as exc:  # noqa: BLE001 - Run 错误需要先转为业务终态
            return "failed", exc

    outcome = ""
    answer = ""
    error: Exception | None = None
    async with asyncio.TaskGroup() as scope:
        task = scope.create_task(attempt_agent())
        lease_task = scope.create_task(
            maintain_lease(run_id, worker_id, redis, task, heartbeat_interval)
        )
        try:
            outcome, value = await task
            if outcome == "completed":
                answer = str(value)
            elif outcome == "failed":
                error = value
        except asyncio.CancelledError:
            if asyncio.current_task().cancelling():
                raise  # Worker shutdown: keep RUNNING for lease-based recovery.
            reason = await lease_task
            outcome = "cancelled" if reason == "cancelled" else "lease_lost"
        finally:
            lease_task.cancel()

    if outcome == "lease_lost":
        return False  # Keep the Redis pending entry for XAUTOCLAIM.
    if outcome == "waiting" and isinstance(value, RunWaiting):
        async with session_factory() as db:
            waiting = await wait_run(db, run_id, worker_id)
        if waiting:
            await safe_publish(events, run_id, "run.waiting", {})
            for approval in value.approvals:
                await safe_publish(events, run_id, "approval.required", approval, record=False)
        return waiting
    if outcome == "completed":
        async with session_factory() as db:
            completed = await finish_run(db, run_id, worker_id, answer)
        if completed:
            await safe_publish(events, run_id, "run.completed", {"answer": answer})
        return completed
    if outcome == "cancelled":
        async with session_factory() as db:
            cancelled = await end_run(db, run_id, worker_id, "CANCELLED", "CANCELLED")
        if cancelled:
            await safe_publish(events, run_id, "run.cancelled", {})
        return cancelled
    if outcome == "failed" and error is not None:
        code = classify_run_error(error)
        if isinstance(error, (BudgetLimitExceeded, RunDeadlineExceeded)):
            budget_event = error.event_data()
        elif isinstance(error, ModelCallLimitExceededError):
            budget_event = {
                "dimension": "model_calls",
                "limit": error.run_limit,
                "used": error.run_count,
            }
        else:
            budget_event = None
        log.error("Run 执行失败", run_id=run_id, error_type=type(error).__name__)
        async with session_factory() as db:
            failed = await end_run(db, run_id, worker_id, "FAILED", code, budget_event)
        if failed:
            await safe_publish(events, run_id, "run.failed", {"code": code})
        return failed
    return False


async def process_entry(
    stream_id: str,
    fields: dict,
    worker_id: str,
    redis: Redis,
    queue: RunQueue,
    events: EventStore,
    saver: AsyncPostgresSaver,
) -> None:
    run_id = fields["run_id"]
    async with session_factory() as db:
        run = await db.get(Run, run_id)
        resumed = run is not None and (
            run.status == "RUNNING" or (run.status == "PENDING" and run.waiting_at is not None)
        )
        claimed = run is not None and await claim_run(db, run_id, worker_id)
    if claimed:
        if await execute_run(run_id, worker_id, resumed, redis, events, saver):
            await queue.ack(stream_id, run_id)
    elif run is None or run.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        await queue.ack(stream_id, run_id)
