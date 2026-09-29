from fastapi import Request
from redis.asyncio import Redis

from app.config import get_settings


def redis_for_request(request: Request) -> tuple[Redis, bool]:
    shared = getattr(request.app.state, "redis", None)
    if shared is not None:
        return shared, False
    # ASGITransport 等不运行 lifespan 的测试客户端使用独立连接。
    return Redis.from_url(get_settings().redis_url, decode_responses=True), True


async def close_if_owned(redis: Redis, owned: bool) -> None:
    if owned:
        await redis.aclose()
