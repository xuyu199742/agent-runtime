from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request

from app.application.auth import Principal
from app.transport.http.common import Approvals, Audit, Runs
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.approval_actions import approval_out, queue_resolved_run
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/approvals", tags=["admin-approvals"])
Viewer = Annotated[Principal, Depends(require("approval:view"))]
Editor = Annotated[Principal, Depends(require("approval:approve"))]


@router.get("")
async def list_approvals(
    _user: Viewer,
    approvals: Approvals,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    status: Literal["PENDING", "APPROVED", "REJECTED", "CANCELLED"] | None = None,
):
    rows, total = await approvals.page(page, page_size, status)
    return {
        "items": [approval_out(row) for row in rows],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{approval_id}")
async def detail(approval_id: str, _user: Viewer, approvals: Approvals):
    return approval_out(await approvals.get(approval_id))


async def decide(
    approval_id: str,
    approve: bool,
    user: Editor,
    runs: Runs,
    approvals: Approvals,
    audit: Audit,
    request: Request,
):
    approval = await approvals.decide(approval_id, user.id, approve)
    await record_action(
        audit,
        request,
        user,
        "approval:approve" if approve else "approval:reject",
        "approval",
        approval_id,
    )
    if await runs.status(approval.run_id) == "PENDING":
        await queue_resolved_run(request, approval.run_id)
    return approval_out(approval)


@router.post("/{approval_id}/approve")
async def approve(
    approval_id: str, user: Editor, runs: Runs, approvals: Approvals, audit: Audit, request: Request
):
    return await decide(approval_id, True, user, runs, approvals, audit, request)


@router.post("/{approval_id}/reject")
async def reject(
    approval_id: str, user: Editor, runs: Runs, approvals: Approvals, audit: Audit, request: Request
):
    return await decide(approval_id, False, user, runs, approvals, audit, request)
