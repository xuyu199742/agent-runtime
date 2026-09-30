from fastapi import APIRouter, Header, Query, Request

from app.transport.http.common import Runs
from app.transport.http.runs import cancel_run_for_user
from app.transport.http.sse import stream_events_for_user
from app.transport.http.v1.dependencies import CurrentUser
from app.transport.schemas.client import ClientRunOut

router = APIRouter(prefix="/api/v1/client/runs", tags=["client-runs"])


def client_run(run, answer):
    return ClientRunOut(
        id=run.id,
        conversation_id=run.session_id,
        status=run.status,
        answer=answer,
        error=run.error_code,
        created_at=run.created_at,
    )


@router.get("/{run_id}", response_model=ClientRunOut)
async def detail(run_id: str, user: CurrentUser, runs: Runs):
    run, answer = await runs.detail(run_id, user.id)
    return client_run(run, answer)


@router.post("/{run_id}/cancel", response_model=ClientRunOut)
async def cancel(run_id: str, user: CurrentUser, runs: Runs, request: Request):
    await cancel_run_for_user(run_id, runs, request, user.id)
    run, answer = await runs.detail(run_id, user.id)
    return client_run(run, answer)


@router.get("/{run_id}/events")
async def events(
    run_id: str,
    user: CurrentUser,
    runs: Runs,
    request: Request,
    after: int = Query(default=0, ge=0),
    last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
):
    return await stream_events_for_user(run_id, request, runs, user.id, after, last_event_id)
