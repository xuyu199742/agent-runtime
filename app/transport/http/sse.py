import json

from fastapi import APIRouter, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from redis.asyncio import Redis

from app.config import get_settings
from app.infrastructure.events import EventStore
from app.transport.http.common import Db
from app.transport.http.runs import visible_run

router = APIRouter()


@router.get("/api/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    db: Db,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    run = await visible_run(db, run_id)
    if after == 0 and last_event_id:
        try:
            after = max(0, int(last_event_id))
        except ValueError:
            raise HTTPException(422, detail="Last-Event-ID 无效") from None
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    events = EventStore(redis)
    first = await events.first_sequence(run_id)
    last = await events.last_sequence(run_id)
    if after > 0 and (first is None or after < first - 1 or after > last):
        await redis.aclose()
        raise HTTPException(410, detail="事件已过期，请读取 Run 最终状态")
    await db.commit()

    async def generate():
        cursor = after
        try:
            while True:
                batch = await events.wait_after(run_id, cursor, block_ms=1000)
                for event in batch:
                    cursor = event.sequence
                    payload = json.dumps(event.as_dict(), ensure_ascii=False)
                    yield f"id: {event.sequence}\nevent: {event.type}\ndata: {payload}\n\n"
                    if event.type in {"run.completed", "run.failed", "run.cancelled"}:
                        return
                if not batch:
                    await db.refresh(run)
                    status = run.status
                    await db.commit()
                    if status in {"COMPLETED", "FAILED", "CANCELLED"}:
                        payload = json.dumps(
                            {
                                "type": "run.snapshot",
                                "run_id": run_id,
                                "sequence": cursor,
                                "data": {"status": status},
                            }
                        )
                        yield f"event: run.snapshot\ndata: {payload}\n\n"
                        return
        finally:
            await redis.aclose()

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
