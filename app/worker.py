import asyncio

import structlog
from redis.asyncio import Redis

from app.config import get_settings


async def main() -> None:
    redis = Redis.from_url(get_settings().redis_url)
    try:
        await redis.ping()
        structlog.get_logger().info("Worker 已启动，等待运行队列接入")
        await asyncio.Event().wait()
    finally:
        await redis.aclose()


if __name__ == "__main__":
    asyncio.run(main())
