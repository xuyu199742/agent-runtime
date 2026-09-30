from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request

from app.application.auth import Principal
from app.transport.http.common import Audit, Runs
from app.transport.http.runs import dispatch_cancel
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/runs", tags=["admin-runs"])
Viewer = Annotated[Principal, Depends(require("run:view"))]
Canceller = Annotated[Principal, Depends(require("run:cancel"))]


def detail_out(run, answer, context):
    user_id, agent_id, agent_name = context
    return {
        "id": run.id,
        "conversation_id": run.session_id,
        "status": run.status,
        "user_id": user_id,
        "agent": {"id": agent_id, "name": agent_name},
        "worker_id": run.lease_owner,
        "answer": answer,
        "error_code": run.error_code,
        "created_at": run.created_at,
        "updated_at": run.updated_at,
    }


@router.get("")
async def list_runs(
    _user: Viewer,
    runs: Runs,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: str | None = None,
    agent_id: str | None = None,
    user_id: str | None = None,
    worker_id: str | None = None,
    error_code: str | None = None,
):
    rows, total = await runs.list_runs(
        page, page_size, user_id, status, agent_id, worker_id, error_code
    )
    return {
        "items": [
            detail_out(run, None, (owner, item_agent_id, agent_name))
            for run, owner, item_agent_id, agent_name in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{run_id}")
async def detail(run_id: str, _user: Viewer, runs: Runs):
    run, answer, context = await runs.admin_detail(run_id)
    return detail_out(run, answer, context)


@router.post("/{run_id}/cancel")
async def cancel(
    run_id: str,
    user: Canceller,
    runs: Runs,
    audit: Audit,
    request: Request,
):
    run, _, _ = await runs.admin_detail(run_id)
    await dispatch_cancel(run_id, run, runs, request)
    await record_action(audit, request, user, "run:cancel", "run", run_id)
    run, answer, context = await runs.admin_detail(run_id)
    return detail_out(run, answer, context)
