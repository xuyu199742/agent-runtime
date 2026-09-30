import asyncio
import os
from uuid import uuid4

from redis.asyncio import Redis

from app.messaging.worker_registry import WorkerActivity, WorkerRegistry, publish_heartbeats


async def test_worker_registry_tracks_capacity_and_expires():
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    worker_id = f"test-{uuid4().hex}"
    registry = WorkerRegistry(redis, ttl_seconds=1)
    activity = WorkerActivity(running=2)
    try:
        await registry.heartbeat(worker_id, "test-host", 4, activity, "started")
        worker = await registry.get(worker_id)
        assert worker["capacity"] == 4 and worker["running"] == 2
        assert worker_id in [item["worker_id"] for item in await registry.list()]
        await asyncio.sleep(1.1)
        assert await registry.get(worker_id) is None
    finally:
        await registry.remove(worker_id)
        await redis.aclose()


async def test_worker_shutdown_removes_registry_entry():
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    worker_id = f"test-{uuid4().hex}"
    registry = WorkerRegistry(redis)
    task = asyncio.create_task(
        publish_heartbeats(registry, worker_id, "test-host", 1, WorkerActivity(), interval=0.01)
    )
    try:
        for _ in range(100):
            if await registry.get(worker_id):
                break
            await asyncio.sleep(0.01)
        assert await registry.get(worker_id)
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        assert await registry.get(worker_id) is None
        await redis.aclose()
