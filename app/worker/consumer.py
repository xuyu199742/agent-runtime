import asyncio

import structlog
from redis.exceptions import RedisError

from app.messaging.run_queue import RunQueue
from app.messaging.worker_registry import WorkerActivity
from app.persistence.database import session_factory
from app.persistence.repositories.runs import pending_run_ids

log = structlog.get_logger()


async def consume_queue(
    queue: RunQueue,
    worker_id: str,
    handler,
    concurrency: int,
    activity: WorkerActivity | None = None,
) -> None:
    """只在有空闲执行槽时领取一条消息，子任务由 TaskGroup 统一管理。"""
    slots = asyncio.Semaphore(concurrency)

    async def handle_entry(stream_id: str, fields: dict) -> None:
        if activity is not None:
            activity.running += 1
        try:
            await handler(stream_id, fields)
        except Exception as exc:  # noqa: BLE001 - 保留消息供 Worker 恢复
            log.error(
                "Run 消费失败，保留未确认消息", stream_id=stream_id, error_type=type(exc).__name__
            )
        finally:
            if activity is not None:
                activity.running -= 1
            slots.release()

    async with asyncio.TaskGroup() as scope:
        while True:
            await slots.acquire()
            try:
                entries = await queue.claim_idle(worker_id, count=1)
                if not entries:
                    entries = await queue.read(worker_id, block_ms=1000, count=1)
            except RedisError as exc:
                slots.release()
                log.warning("Run Queue 暂不可用", error_type=type(exc).__name__)
                await asyncio.sleep(1)
                continue
            except BaseException:
                slots.release()
                raise
            if entries:
                stream_id, fields = entries[0]
                scope.create_task(handle_entry(stream_id, fields))
            else:
                slots.release()


async def sweep_pending(queue: RunQueue) -> None:
    while True:
        try:
            cursor = None
            while True:
                async with session_factory() as db:
                    page = await pending_run_ids(db, after=cursor)
                for run_id in page:
                    await queue.enqueue(run_id)
                if len(page) < 100:
                    break
                cursor = page[-1]
        except Exception as exc:  # noqa: BLE001 - 补投循环需持续重试
            log.warning("PENDING Run 补投暂不可用", error_type=type(exc).__name__)
        await asyncio.sleep(10)
