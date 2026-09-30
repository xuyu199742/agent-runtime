"""Worker 实时状态以 Redis TTL 为准。"""

import asyncio
import json
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from redis.asyncio import Redis
from redis.exceptions import RedisError

log = structlog.get_logger()


@dataclass
class WorkerActivity:
    running: int = 0


class WorkerRegistry:
    def __init__(self, redis: Redis, ttl_seconds: int = 15):
        self.redis = redis
        self.ttl_seconds = ttl_seconds

    @staticmethod
    def key(worker_id: str) -> str:
        return f"worker:{worker_id}"

    async def heartbeat(
        self,
        worker_id: str,
        hostname: str,
        capacity: int,
        activity: WorkerActivity,
        started_at: str,
    ):
        now = datetime.now(UTC).isoformat()
        payload = {
            "worker_id": worker_id,
            "hostname": hostname,
            "runtime_version": "0.2",
            "capacity": capacity,
            "running": activity.running,
            "started_at": started_at,
            "heartbeat_at": now,
        }
        await self.redis.set(self.key(worker_id), json.dumps(payload), ex=self.ttl_seconds)

    async def get(self, worker_id: str) -> dict | None:
        value = await self.redis.get(self.key(worker_id))
        return json.loads(value) if value else None

    async def list(self) -> list[dict]:
        keys = [key async for key in self.redis.scan_iter(match="worker:*")]
        if not keys:
            return []
        values = await self.redis.mget(keys)
        return sorted(
            [json.loads(value) for value in values if value],
            key=lambda item: item["worker_id"],
        )

    async def remove(self, worker_id: str) -> None:
        await self.redis.delete(self.key(worker_id))


async def publish_heartbeats(
    registry: WorkerRegistry,
    worker_id: str,
    hostname: str,
    capacity: int,
    activity: WorkerActivity,
    interval: float = 5,
) -> None:
    started_at = datetime.now(UTC).isoformat()
    try:
        while True:
            try:
                await registry.heartbeat(worker_id, hostname, capacity, activity, started_at)
            except RedisError:
                log.warning("Worker 心跳暂不可用", worker_id=worker_id)
            await asyncio.sleep(interval)
    finally:
        try:
            await registry.remove(worker_id)
        except RedisError:
            pass  # TTL 会自动清理。
