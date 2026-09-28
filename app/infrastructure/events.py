import json
from dataclasses import dataclass
from datetime import UTC, datetime

from redis.asyncio import Redis

_PUBLISH_SCRIPT = """
local sequence = redis.call('INCR', KEYS[2])
redis.call('XADD', KEYS[1], sequence .. '-0', 'type', ARGV[1], 'timestamp', ARGV[2], 'data', ARGV[3])
return sequence
"""
_TERMINAL = {"run.completed", "run.failed", "run.cancelled"}


@dataclass(frozen=True)
class RunEvent:
    type: str
    run_id: str
    sequence: int
    timestamp: str
    data: dict

    def as_dict(self) -> dict:
        return {
            "type": self.type,
            "run_id": self.run_id,
            "sequence": self.sequence,
            "timestamp": self.timestamp,
            "data": self.data,
        }


class EventStore:
    def __init__(self, redis: Redis, retention_seconds: int = 86400):
        self.redis = redis
        self.retention_seconds = retention_seconds

    @staticmethod
    def key(run_id: str) -> str:
        return f"run:{run_id}:events"

    @staticmethod
    def sequence_key(run_id: str) -> str:
        return f"run:{run_id}:sequence"

    async def publish(self, run_id: str, kind: str, data: dict) -> RunEvent:
        timestamp = datetime.now(UTC).isoformat()
        sequence = await self.redis.eval(
            _PUBLISH_SCRIPT,
            2,
            self.key(run_id),
            self.sequence_key(run_id),
            kind,
            timestamp,
            json.dumps(data, ensure_ascii=False),
        )
        if kind in _TERMINAL:
            await self.redis.expire(self.key(run_id), self.retention_seconds)
            await self.redis.expire(self.sequence_key(run_id), self.retention_seconds)
        return RunEvent(kind, run_id, int(sequence), timestamp, data)

    def decode(self, run_id: str, stream_id: str, fields: dict) -> RunEvent:
        return RunEvent(
            type=fields["type"],
            run_id=run_id,
            sequence=int(stream_id.split("-", 1)[0]),
            timestamp=fields["timestamp"],
            data=json.loads(fields["data"]),
        )

    async def read_after(self, run_id: str, after: int) -> list[RunEvent]:
        records = await self.redis.xrange(self.key(run_id), min=f"({after}-0")
        return [self.decode(run_id, stream_id, fields) for stream_id, fields in records]

    async def wait_after(self, run_id: str, after: int, block_ms: int = 1000) -> list[RunEvent]:
        rows = await self.redis.xread({self.key(run_id): f"{after}-0"}, block=block_ms, count=100)
        return [
            self.decode(run_id, stream_id, fields)
            for _key, entries in rows
            for stream_id, fields in entries
        ]

    async def first_sequence(self, run_id: str) -> int | None:
        rows = await self.redis.xrange(self.key(run_id), count=1)
        return int(rows[0][0].split("-", 1)[0]) if rows else None
