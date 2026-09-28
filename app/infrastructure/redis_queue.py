from redis.asyncio import Redis
from redis.exceptions import ResponseError

_ENQUEUE_SCRIPT = """
if redis.call('SET', KEYS[2], '1', 'EX', 30, 'NX') then
  redis.call('XADD', KEYS[1], '*', 'run_id', ARGV[1])
  return 1
end
return 0
"""


class RunQueue:
    def __init__(self, redis: Redis, stream: str = "agent:runs", group: str = "agent-workers"):
        self.redis = redis
        self.stream = stream
        self.group = group

    async def ensure_group(self) -> None:
        try:
            await self.redis.xgroup_create(self.stream, self.group, id="0-0", mkstream=True)
        except ResponseError as exc:
            if "BUSYGROUP" not in str(exc):
                raise

    async def enqueue(self, run_id: str) -> bool:
        result = await self.redis.eval(
            _ENQUEUE_SCRIPT, 2, self.stream, f"run:{run_id}:enqueued", run_id
        )
        return bool(result)

    async def read(self, consumer: str, block_ms: int = 5000) -> list[tuple[str, dict]]:
        rows = await self.redis.xreadgroup(
            self.group, consumer, {self.stream: ">"}, count=10, block=block_ms
        )
        return [(stream_id, fields) for _stream, entries in rows for stream_id, fields in entries]

    async def claim_idle(self, consumer: str, min_idle_ms: int = 60000) -> list[tuple[str, dict]]:
        _cursor, entries, _deleted = await self.redis.xautoclaim(
            self.stream, self.group, consumer, min_idle_ms, "0-0", count=10
        )
        return entries

    async def ack(self, stream_id: str) -> None:
        await self.redis.xack(self.stream, self.group, stream_id)
