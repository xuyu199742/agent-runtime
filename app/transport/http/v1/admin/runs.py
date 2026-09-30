from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request
from redis.exceptions import RedisError

from app.application.auth import Principal
from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.run_queue import RunQueue
from app.transport.http.common import Artifacts, Audit, Runs
from app.transport.http.runs import dispatch_cancel
from app.transport.http.v1.admin.common import record_action
from app.transport.http.v1.artifact_views import artifact_page
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/runs", tags=["admin-runs"])
Viewer = Annotated[Principal, Depends(require("run:view"))]
ArtifactViewer = Annotated[Principal, Depends(require("artifact:view"))]
Canceller = Annotated[Principal, Depends(require("run:cancel"))]
Retrier = Annotated[Principal, Depends(require("run:retry"))]


def detail_out(run, answer, context):
    user_id, agent_id, agent_name = context
    return {
        "id": run.id,
        "conversation_id": run.session_id,
        "status": run.status,
        "user_id": user_id,
        "agent": {"id": agent_id, "name": agent_name},
        "worker_id": run.worker_id,
        "execution_spec_id": run.execution_spec_id,
        "runtime_version": run.runtime_version,
        "parent_run_id": run.parent_run_id,
        "attempt": run.attempt,
        "origin": run.origin,
        "started_at": run.started_at,
        "completed_at": run.completed_at,
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


@router.get("/{run_id}/execution-spec")
async def execution_spec(run_id: str, _user: Viewer, runs: Runs):
    return await runs.execution_spec(run_id)


@router.get("/{run_id}/tool-executions")
async def tool_executions(run_id: str, _user: Viewer, runs: Runs):
    rows = await runs.tool_executions(run_id)
    return [
        {
            "id": row.id,
            "tool_call_id": row.tool_call_id,
            "tool_name": row.tool_name,
            "effect_type": row.effect_type,
            "idempotency_key": row.idempotency_key,
            "args_hash": row.args_hash,
            "status": row.status,
            "attempt": row.attempt,
            "error_code": row.error_code,
            "started_at": row.started_at,
            "completed_at": row.completed_at,
        }
        for row in rows
    ]


@router.get("/{run_id}/trace")
async def trace(
    run_id: str,
    _user: Viewer,
    runs: Runs,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
):
    await runs.admin_detail(run_id)
    rows, total = await runs.trace(run_id, page, page_size)
    return {
        "items": [
            {"id": row.id, "type": row.event_type, "data": row.data, "created_at": row.created_at}
            for row in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{run_id}/artifacts")
async def artifacts_for_run(
    run_id: str,
    _user: Viewer,
    _artifact_user: ArtifactViewer,
    runs: Runs,
    artifacts: Artifacts,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    await runs.admin_detail(run_id)
    rows, total = await artifacts.run(run_id, page, page_size)
    return artifact_page(rows, total, page, page_size)


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


@router.post("/{run_id}/retry", status_code=202)
async def retry(run_id: str, user: Retrier, runs: Runs, audit: Audit, request: Request):
    retry_run = await runs.retry(run_id)
    redis, owned = redis_for_request(request)
    try:
        await RunQueue(redis).enqueue(retry_run.id)
    except RedisError:
        pass  # PENDING 补投任务会重新投递。
    finally:
        await close_if_owned(redis, owned)
    await record_action(audit, request, user, "run:retry", "run", retry_run.id)
    return {"id": retry_run.id, "parent_run_id": run_id, "status": retry_run.status}
