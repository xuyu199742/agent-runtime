from fastapi import APIRouter, Request

from app.transport.http.common import Approvals, Runs
from app.transport.http.v1.approval_actions import approval_out, queue_resolved_run
from app.transport.http.v1.dependencies import CurrentUser

router = APIRouter(prefix="/api/v1/client", tags=["client-approvals"])


@router.get("/runs/{run_id}/approvals")
async def list_approvals(run_id: str, user: CurrentUser, runs: Runs, approvals: Approvals):
    await runs.visible(run_id, user.id)
    return [approval_out(row) for row in await approvals.for_run(run_id)]


async def decide(
    approval_id: str,
    approve: bool,
    user: CurrentUser,
    runs: Runs,
    approvals: Approvals,
    request: Request,
):
    approval = await approvals.get(approval_id)
    await runs.visible(approval.run_id, user.id)
    approval = await approvals.decide(approval_id, user.id, approve)
    if await runs.status(approval.run_id) == "PENDING":
        await queue_resolved_run(request, approval.run_id)
    return approval_out(approval)


@router.post("/approvals/{approval_id}/approve")
async def approve(
    approval_id: str, user: CurrentUser, runs: Runs, approvals: Approvals, request: Request
):
    return await decide(approval_id, True, user, runs, approvals, request)


@router.post("/approvals/{approval_id}/reject")
async def reject(
    approval_id: str, user: CurrentUser, runs: Runs, approvals: Approvals, request: Request
):
    return await decide(approval_id, False, user, runs, approvals, request)
