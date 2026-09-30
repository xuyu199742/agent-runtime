import asyncio

import httpx
import openai
import structlog
from langchain.agents.middleware.model_call_limit import ModelCallLimitExceededError
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.exc import SQLAlchemyError

from app.config import get_settings
from app.domain.agent import ModelDefinition, ToolDefinition
from app.domain.session import ConversationTurn
from app.messaging.events import EventStore
from app.messaging.run_queue import RunQueue
from app.persistence.database import (
    AgentDefinition,
    ExecutionSpec,
    ModelConfig,
    Run,
    Session,
    session_factory,
)
from app.persistence.repositories.approvals import ApprovalRepository
from app.persistence.repositories.conversations import ConversationRepository
from app.persistence.repositories.runs import claim_run, end_run, extend_lease, finish_run, wait_run
from app.persistence.repositories.tool_executions import ToolExecutionStore
from app.runtime.agent import LangChainAgentRuntime, RunCancelled, RunWaiting
from app.runtime.context import build_context
from app.runtime.factory import build_model, resolve_model_config
from app.runtime.tools import ToolConfigurationError, build_tools

log = structlog.get_logger()


class CoordinationLost(Exception):
    """运行协调层暂不可用，保留 RUNNING 与未 ACK 消息供恢复。"""


def classify_run_error(exc: Exception) -> str:
    if isinstance(exc, ModelCallLimitExceededError):
        return "VALIDATION_ERROR"
    if isinstance(exc, (TimeoutError, httpx.TimeoutException, openai.APITimeoutError)):
        return "TIMEOUT"
    if isinstance(exc, ToolConfigurationError):
        return "TOOL_ERROR"
    if isinstance(exc, (openai.APIError, httpx.HTTPError, ValueError)):
        return "MODEL_ERROR"
    if isinstance(exc, (RedisError, SQLAlchemyError, OSError)):
        return "INTERNAL_ERROR"
    return "INTERNAL_ERROR"


async def safe_publish(events: EventStore, run_id: str, kind: str, data: dict) -> None:
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
        snapshot = spec.snapshot if spec else None
        agent = await db.get(AgentDefinition, session.agent_id) if snapshot is None else None
        model_config = await db.get(ModelConfig, agent.model_id) if agent is not None else None
        context_policy = (
            snapshot["context"]
            if snapshot
            else {
                "max_messages": get_settings().context_max_messages,
                "max_tokens": get_settings().context_max_tokens,
            }
        )
        history = await ConversationRepository(db).recent_messages(
            session.id, run.created_at, context_policy["max_messages"]
        )

    structlog.contextvars.clear_contextvars()
    log_context = {
        "request_id": run_id,
        "run_id": run_id,
        "session_id": session.id,
        "user_id": session.user_id,
    }
    if worker_id is not None:
        log_context["worker_id"] = worker_id
    structlog.contextvars.bind_contextvars(**log_context)

    if not resumed:
        await safe_publish(events, run_id, "run.started", {})
    model_data = (
        snapshot["model"]
        if snapshot
        else {
            "provider": model_config.provider,
            "model_name": model_config.model_name,
            "base_url": model_config.base_url,
            "config": model_config.config,
            "api_key_encrypted": model_config.api_key_encrypted,
        }
    )
    tool_data = (
        snapshot["tools"]
        if snapshot
        else [
            {
                "name": tool.name,
                "type": tool.type,
                "description": tool.description,
                "config": tool.config,
                "policy": tool.policy,
                "effect_type": tool.effect_type,
                "failure_policy": tool.failure_policy,
            }
            for tool in agent.tools
        ]
    )
    runtime = LangChainAgentRuntime(
        model=build_model(
            resolve_model_config(
                ModelDefinition(
                    provider=model_data["provider"],
                    model_name=model_data["model_name"],
                    base_url=model_data["base_url"],
                    config=model_data["config"],
                    enabled=True if snapshot else model_config.enabled,
                ),
                model_data["api_key_encrypted"],
            )
        ),
        tools=build_tools(
            [
                ToolDefinition(
                    name=tool["name"],
                    type=tool["type"],
                    description=tool["description"],
                    config=tool["config"],
                    policy=tool["policy"],
                    enabled=True,
                )
                for tool in tool_data
            ]
        ),
        system_prompt=snapshot["system_prompt"] if snapshot else agent.system_prompt,
        max_model_calls=snapshot["max_model_calls"] if snapshot else agent.max_model_calls,
        checkpointer=saver,
        tool_execution_store=ToolExecutionStore(session_factory),
        run_id=run_id,
        tool_policies={tool["name"]: tool for tool in tool_data},
        approval_session_factory=session_factory,
    )

    approval_decisions = None
    if resumed:
        state = await runtime.graph.aget_state({"configurable": {"thread_id": run_id}})
        if state.interrupts:
            decisions = {}
            async with session_factory() as db:
                approvals = ApprovalRepository(db)
                for pending in state.interrupts:
                    approval = await approvals.get(pending.value["approval_id"])
                    if approval is not None and approval.status in {"APPROVED", "REJECTED"}:
                        decisions[pending.id] = approval.status == "APPROVED"
            if len(decisions) == len(state.interrupts):
                approval_decisions = decisions

    async def emit(kind: str, data: dict) -> None:
        await safe_publish(events, run_id, kind, data)

    async def should_cancel() -> bool:
        try:
            return bool(await redis.exists(f"run:{run_id}:cancel"))
        except RedisError as exc:
            raise CoordinationLost from exc

    return await runtime.run(
        run_id,
        build_context(
            [ConversationTurn(role=item.role, content=item.content) for item in history],
            max_messages=context_policy["max_messages"],
            max_tokens=context_policy["max_tokens"],
        ),
        emit,
        should_cancel,
        session_id=session.id,
        user_id=session.user_id,
        resume=resumed,
        approval_decisions=approval_decisions,
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
        except CoordinationLost:
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
                await safe_publish(events, run_id, "approval.required", approval)
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
        log.error("Run 执行失败", run_id=run_id, error_type=type(error).__name__)
        async with session_factory() as db:
            failed = await end_run(db, run_id, worker_id, "FAILED", code)
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
