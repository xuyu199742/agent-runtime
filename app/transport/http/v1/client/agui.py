"""基于 PostgreSQL Run 事实的 AG-UI 1.0 SSE 适配端点。"""

import asyncio
import json

from fastapi import APIRouter, Header, HTTPException, Query, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import select

from app.persistence.database import Approval, Message, Run, RunTraceEvent, session_factory
from app.transport.agui import map_trace_event, run_started, terminal_events
from app.transport.http.common import Runs
from app.transport.http.v1.dependencies import CurrentUser

router = APIRouter(prefix="/api/v1/client/runs", tags=["client-ag-ui"])
TERMINAL = {"COMPLETED", "FAILED", "CANCELLED", "WAITING"}


def _sse(event: dict, event_id: str | None = None) -> str:
    prefix = f"id: {event_id}\n" if event_id is not None else ""
    return f"{prefix}event: {event['type']}\ndata: {json.dumps(event, ensure_ascii=False)}\n\n"


def _cursor(after: str | None) -> tuple[int, bool, int]:
    if after is None:
        return 0, False, -1
    parts = after.split(":")
    if len(parts) == 2 and all(part.isdecimal() for part in parts):
        return int(parts[0]), False, int(parts[1])
    if len(parts) == 3 and parts[1] == "t" and parts[0].isdecimal() and parts[2].isdecimal():
        return int(parts[0]), True, int(parts[2])
    raise HTTPException(422, detail="AG-UI Event ID 无效")


@router.get("/{run_id}/ag-ui/events")
async def stream_agui(
    run_id: str,
    request: Request,
    user: CurrentUser,
    runs: Runs,
    after: str | None = Query(default=None),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    run = await runs.visible(run_id, user.id)
    thread_id = run.session_id
    await runs.release_read()
    cursor_sequence, cursor_terminal, cursor_index = _cursor(last_event_id or after)

    async def generate():
        nonlocal cursor_sequence, cursor_terminal, cursor_index
        if cursor_sequence == 0:
            yield _sse(run_started(thread_id, run_id))
        while not await request.is_disconnected():
            async with session_factory() as db:
                current = await db.get(Run, run_id)
                rows = list(
                    (
                        await db.scalars(
                            select(RunTraceEvent)
                            .where(
                                RunTraceEvent.run_id == run_id,
                                RunTraceEvent.sequence >= cursor_sequence,
                            )
                            .order_by(RunTraceEvent.sequence)
                            .limit(100)
                        )
                    ).all()
                )
                answer = (
                    await db.get(Message, current.answer_message_id)
                    if current.answer_message_id
                    else None
                )
                approvals = (
                    list(
                        (
                            await db.scalars(
                                select(Approval).where(
                                    Approval.run_id == run_id, Approval.status == "PENDING"
                                )
                            )
                        ).all()
                    )
                    if current.status == "WAITING"
                    else []
                )
                status = current.status
                trace_sequence = current.trace_sequence
                error_code = current.error_code
                answer_id = current.answer_message_id
                answer_text = answer.content if answer is not None else None
            for row in rows:
                if row.sequence < cursor_sequence:
                    continue
                replayed_terminal = row.sequence == cursor_sequence and cursor_terminal
                mapped = map_trace_event(row)
                # 旧版 WAITING 终态用下一条 trace 的 0 号索引；升级后允许审批事件重放一次。
                legacy_approval_overlap = (
                    row.sequence == cursor_sequence
                    and not cursor_terminal
                    and cursor_index == 0
                    and row.event_type in {"approval.approved", "approval.rejected"}
                )
                for index, event in enumerate(mapped):
                    if replayed_terminal or (
                        row.sequence == cursor_sequence
                        and index <= cursor_index
                        and not legacy_approval_overlap
                    ):
                        continue
                    yield _sse(event, f"{row.sequence}:{index}")
                if not replayed_terminal:
                    cursor_sequence, cursor_terminal, cursor_index = (
                        row.sequence,
                        False,
                        max(len(mapped) - 1, 0),
                    )
            if status in TERMINAL and (not rows or rows[-1].sequence >= trace_sequence):
                terminal = terminal_events(
                    thread_id,
                    run_id,
                    status,
                    answer_id,
                    answer_text,
                    error_code,
                    [
                        {
                            "id": item.id,
                            "tool_call_id": item.tool_call_id,
                            "title": item.title,
                            "risk": item.risk,
                            "status": item.status,
                        }
                        for item in approvals
                    ],
                )
                for index, event in enumerate(terminal):
                    if (
                        trace_sequence == cursor_sequence
                        and cursor_terminal
                        and index <= cursor_index
                    ):
                        continue
                    yield _sse(event, f"{trace_sequence}:t:{index}")
                return
            if len(rows) < 100:
                await asyncio.sleep(0.5)

    return StreamingResponse(
        generate(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"}
    )
