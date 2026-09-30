import json

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse

from app.config import get_settings
from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.events import EventStore
from app.transport.http.common import Runs

router = APIRouter()


@router.get("/api/runs/{run_id}/events")
async def stream_events(
    run_id: str,
    request: Request,
    runs: Runs,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    return await stream_events_for_user(
        run_id, request, runs, get_settings().dev_user_id, after, last_event_id
    )


async def stream_events_for_user(
    run_id: str,
    request: Request,
    runs: Runs,
    user_id: str,
    after: int = 0,
    last_event_id: str | None = None,
):
    await runs.visible(run_id, user_id)
    await runs.release_read()
    if after == 0 and last_event_id:
        try:
            after = max(0, int(last_event_id))
        except ValueError:
            raise HTTPException(422, detail="Last-Event-ID 无效") from None
    redis, owned = redis_for_request(request)
    events = EventStore(redis)
    first = await events.first_sequence(run_id)
    last = await events.last_sequence(run_id)
    if after > 0 and (first is None or after < first - 1 or after > last):
        await close_if_owned(redis, owned)
        raise HTTPException(410, detail="事件已过期，请读取 Run 最终状态")

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
                    status = await runs.status(run_id)
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
            await close_if_owned(redis, owned)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
