import asyncio
import socket
from datetime import UTC, datetime

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver
from langgraph.errors import GraphRecursionError
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select

from app.application.runs import claim_run, end_run, extend_lease, finish_run, pending_run_ids
from app.config import get_settings
from app.infrastructure.database import (
    AgentDefinition,
    Message,
    ModelConfig,
    Run,
    Session,
    session_factory,
)
from app.infrastructure.events import EventStore
from app.infrastructure.redis_queue import RunQueue
from app.runtime.agent import LangChainAgentRuntime, RunCancelled
from app.runtime.context import build_context
from app.runtime.factory import build_model
from app.runtime.tools import build_tools

log = structlog.get_logger()


async def safe_publish(events: EventStore, run_id: str, kind: str, data: dict) -> None:
    try:
        await events.publish(run_id, kind, data)
    except RedisError:
        log.warning("事件投递失败", run_id=run_id, event_type=kind)


async def maintain_lease(run_id: str, worker_id: str, redis: Redis, task: asyncio.Task) -> None:
    while not task.done():
        await asyncio.sleep(2)
        if await redis.exists(f"run:{run_id}:cancel"):
            task.cancel()
            return
        async with session_factory() as db:
            if not await extend_lease(db, run_id, worker_id):
                task.cancel()
                return


async def run_agent(
    run_id: str,
    resumed: bool,
    redis: Redis,
    events: EventStore,
    saver: AsyncPostgresSaver,
) -> str:
    async with session_factory() as db:
        run = await db.get(Run, run_id)
        session = await db.get(Session, run.session_id)
        agent = await db.get(AgentDefinition, session.agent_id)
        model_config = await db.get(ModelConfig, agent.model_id)
        history = list(
            (
                await db.scalars(
                    select(Message)
                    .where(Message.session_id == session.id, Message.created_at <= run.created_at)
                    .order_by(Message.created_at, Message.id)
                )
            ).all()
        )

    if not resumed:
        await safe_publish(events, run_id, "run.started", {})
    runtime = LangChainAgentRuntime(
        model=build_model(model_config),
        tools=build_tools(agent.tools),
        system_prompt=agent.system_prompt,
        max_steps=agent.max_steps,
        checkpointer=saver,
    )

    async def emit(kind: str, data: dict) -> None:
        await safe_publish(events, run_id, kind, data)

    async def should_cancel() -> bool:
        return bool(await redis.exists(f"run:{run_id}:cancel"))

    return await runtime.run(
        run_id,
        build_context(history),
        emit,
        should_cancel,
        session_id=session.id,
        user_id=session.user_id,
        resume=resumed,
    )


async def execute_run(
    run_id: str,
    worker_id: str,
    resumed: bool,
    redis: Redis,
    events: EventStore,
    saver: AsyncPostgresSaver,
) -> None:
    task = asyncio.create_task(run_agent(run_id, resumed, redis, events, saver))
    lease_task = asyncio.create_task(maintain_lease(run_id, worker_id, redis, task))
    try:
        answer = await task
        async with session_factory() as db:
            completed = await finish_run(db, run_id, worker_id, answer)
        if completed:
            await safe_publish(events, run_id, "run.completed", {"answer": answer})
    except (RunCancelled, asyncio.CancelledError):
        async with session_factory() as db:
            cancelled = await end_run(db, run_id, worker_id, "CANCELLED", "CANCELLED")
        if cancelled:
            await safe_publish(events, run_id, "run.cancelled", {})
    except Exception as exc:
        code = "TIMEOUT" if isinstance(exc, TimeoutError) else "MODEL_ERROR"
        if isinstance(exc, GraphRecursionError):
            code = "MODEL_ERROR"
        log.exception("Run 执行失败", run_id=run_id, error_type=type(exc).__name__)
        async with session_factory() as db:
            failed = await end_run(db, run_id, worker_id, "FAILED", code)
        if failed:
            await safe_publish(events, run_id, "run.failed", {"code": code})
    finally:
        lease_task.cancel()
        try:
            await lease_task
        except asyncio.CancelledError:
            pass


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
        resumed = run is not None and run.status == "RUNNING"
        claimed = run is not None and await claim_run(db, run_id, worker_id)
    if claimed:
        await execute_run(run_id, worker_id, resumed, redis, events, saver)
        await queue.ack(stream_id)
    elif run is None or run.status in {"COMPLETED", "FAILED", "CANCELLED"}:
        await queue.ack(stream_id)


async def main() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = RunQueue(redis)
    events = EventStore(redis)
    worker_id = f"{socket.gethostname()}-{datetime.now(UTC).timestamp()}"
    try:
        await queue.ensure_group()
        async with AsyncPostgresSaver.from_conn_string(settings.checkpoint_database_url) as saver:
            await saver.setup()
            last_sweep = 0.0
            while True:
                now = asyncio.get_running_loop().time()
                if now - last_sweep >= 10:
                    async with session_factory() as db:
                        for run_id in await pending_run_ids(db):
                            await queue.enqueue(run_id)
                    last_sweep = now
                for stream_id, fields in await queue.claim_idle(worker_id):
                    await process_entry(stream_id, fields, worker_id, redis, queue, events, saver)
                for stream_id, fields in await queue.read(worker_id, block_ms=1000):
                    await process_entry(stream_id, fields, worker_id, redis, queue, events, saver)
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
