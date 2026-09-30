import asyncio
import socket
from datetime import UTC, datetime

from redis.asyncio import Redis

from app.config import get_settings
from app.infrastructure.logging import configure_logging
from app.messaging.events import EventStore
from app.messaging.run_queue import RunQueue
from app.messaging.worker_registry import WorkerActivity, WorkerRegistry, publish_heartbeats
from app.persistence.database import engine
from app.runtime.checkpoint import create_checkpoint_pool, create_saver
from app.worker.consumer import consume_queue, sweep_pending
from app.worker.retention import sweep_checkpoints
from app.worker.runner import process_entry

configure_logging()


async def main() -> None:
    settings = get_settings()
    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    queue = RunQueue(redis)
    events = EventStore(redis)
    worker_id = f"{socket.gethostname()}-{datetime.now(UTC).timestamp()}"
    activity = WorkerActivity()
    registry = WorkerRegistry(redis)
    try:
        await queue.ensure_group()
        pool = create_checkpoint_pool(settings.checkpoint_database_url, settings.worker_concurrency)
        async with pool:
            saver = create_saver(pool)
            await saver.setup()

            async def handler(stream_id: str, fields: dict) -> None:
                # 每个 Run 一个 saver 实例，连接由官方 psycopg pool 分配。
                await process_entry(
                    stream_id, fields, worker_id, redis, queue, events, create_saver(pool)
                )

            async with asyncio.TaskGroup() as scope:
                scope.create_task(
                    publish_heartbeats(
                        registry,
                        worker_id,
                        socket.gethostname(),
                        settings.worker_concurrency,
                        activity,
                    )
                )
                scope.create_task(sweep_pending(queue))
                scope.create_task(sweep_checkpoints(saver, settings.checkpoint_retention_hours))
                scope.create_task(
                    consume_queue(queue, worker_id, handler, settings.worker_concurrency, activity)
                )
    finally:
        await redis.aclose()
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
