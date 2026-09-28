import os
from uuid import uuid4

from redis.asyncio import Redis

from app.infrastructure.events import EventStore
from app.infrastructure.redis_queue import RunQueue


async def test_event_stream_replays_after_sequence():
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    run_id = f"test-{uuid4()}"
    try:
        store = EventStore(redis)
        await store.publish(run_id, "run.started", {})
        await store.publish(run_id, "model.delta", {"text": "A"})
        await store.publish(run_id, "model.delta", {"text": "B"})
        replay = await store.read_after(run_id, after=1)
        assert [(event.sequence, event.data.get("text")) for event in replay] == [
            (2, "A"),
            (3, "B"),
        ]
    finally:
        await redis.delete(f"run:{run_id}:events", f"run:{run_id}:sequence")
        await redis.aclose()


async def test_queue_delivers_and_acknowledges_run():
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    queue = RunQueue(redis, stream=f"test:runs:{uuid4()}", group="test-workers")
    run_id = f"run-{uuid4()}"
    try:
        await queue.ensure_group()
        await queue.enqueue(run_id)
        messages = await queue.read("worker-1", block_ms=100)
        assert messages[0][1]["run_id"] == run_id
        await queue.ack(messages[0][0])
        assert await queue.read("worker-2", block_ms=100) == []
    finally:
        await redis.delete(queue.stream)
        await redis.aclose()


async def test_unacknowledged_queue_entry_can_be_reclaimed():
    redis = Redis.from_url(os.environ["TEST_REDIS_URL"], decode_responses=True)
    queue = RunQueue(redis, stream=f"test:reclaim:{uuid4()}", group="test-workers")
    run_id = f"run-{uuid4()}"
    try:
        await queue.ensure_group()
        await queue.enqueue(run_id)
        original = await queue.read("worker-a", block_ms=100)
        reclaimed = await queue.claim_idle("worker-b", min_idle_ms=0)
        assert reclaimed == original
        await queue.ack(reclaimed[0][0])
    finally:
        await redis.delete(queue.stream)
        await redis.aclose()
