from fastapi import Request
from redis.exceptions import RedisError

from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.run_queue import RunQueue


def approval_out(row):
    return {
        "id": row.id,
        "run_id": row.run_id,
        "title": row.title,
        "description": row.description,
        "risk": row.risk,
        "tool_name": row.tool_name,
        "status": row.status,
        "created_at": row.created_at,
        "decided_at": row.decided_at,
    }


async def queue_resolved_run(request: Request, run_id: str) -> None:
    redis, owned = redis_for_request(request)
    try:
        await RunQueue(redis).enqueue(run_id)
    except RedisError:
        pass  # PENDING 补投任务继续兜底。
    finally:
        await close_if_owned(redis, owned)
