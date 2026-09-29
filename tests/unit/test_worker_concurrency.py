import asyncio

import pytest

from app.worker.consumer import consume_queue


async def test_consumer_runs_multiple_entries_with_a_hard_limit():
    pending = [(str(i), {"run_id": str(i)}) for i in range(4)]
    running = 0
    peak = 0
    started = asyncio.Event()
    release = asyncio.Event()
    finished = asyncio.Event()
    completed = 0

    class Queue:
        async def claim_idle(self, _consumer, count=1):
            return []

        async def read(self, _consumer, block_ms=1000, count=1):
            if pending:
                return [pending.pop(0)]
            await asyncio.sleep(0.01)
            return []

    async def handle(_stream_id, _fields):
        nonlocal running, peak, completed
        running += 1
        peak = max(peak, running)
        if running == 2:
            started.set()
        try:
            await release.wait()
        finally:
            running -= 1
            completed += 1
            if completed == 4:
                finished.set()

    consumer = asyncio.create_task(consume_queue(Queue(), "worker", handle, concurrency=2))
    try:
        await asyncio.wait_for(started.wait(), 1)
        assert peak == 2
        assert len(pending) == 2
        release.set()
        await asyncio.wait_for(finished.wait(), 1)
        assert peak == 2
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer


async def test_one_run_failure_does_not_stop_consumer():
    pending = [("bad", {}), ("good", {})]
    handled = []
    done = asyncio.Event()

    class Queue:
        async def claim_idle(self, _consumer, count=1):
            return []

        async def read(self, _consumer, block_ms=1000, count=1):
            if pending:
                return [pending.pop(0)]
            await asyncio.sleep(0.01)
            return []

    async def handle(stream_id, _fields):
        handled.append(stream_id)
        if stream_id == "bad":
            raise RuntimeError("one run failed")
        done.set()

    consumer = asyncio.create_task(consume_queue(Queue(), "worker", handle, concurrency=1))
    try:
        await asyncio.wait_for(done.wait(), 1)
        assert handled == ["bad", "good"]
    finally:
        consumer.cancel()
        with pytest.raises(asyncio.CancelledError):
            await consumer
