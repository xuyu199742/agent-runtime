import structlog
from fastapi import APIRouter, HTTPException, Request
from redis.exceptions import RedisError

from app.config import get_settings
from app.domain.errors import Conflict
from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.events import EventStore
from app.transport.http.common import Runs
from app.transport.schemas import RunOut

log = structlog.get_logger()

router = APIRouter()


@router.get("/api/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, runs: Runs):
    return await get_run_for_user(run_id, runs, get_settings().dev_user_id)


async def get_run_for_user(run_id: str, runs: Runs, user_id: str):
    run, answer = await runs.detail(run_id, user_id)
    result = RunOut.model_validate(run)
    result.answer = answer
    return result


@router.post("/api/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: str, runs: Runs, request: Request):
    return await cancel_run_for_user(run_id, runs, request, get_settings().dev_user_id)


async def cancel_run_for_user(run_id: str, runs: Runs, request: Request, user_id: str):
    run = await runs.visible(run_id, user_id)
    await dispatch_cancel(run_id, run, runs, request)
    return await get_run_for_user(run_id, runs, user_id)


async def dispatch_cancel(run_id: str, run, runs: Runs, request: Request) -> None:
    redis, owned = redis_for_request(request)
    try:
        if run.status == "PENDING" and await runs.cancel_pending(run_id):
            try:
                await EventStore(redis).publish(run_id, "run.cancelled", {})
            except RedisError:
                log.warning("取消事件投递失败，可从 Run 状态恢复", run_id=run_id)
            return
        status = await runs.status(run_id)
        if status == "RUNNING":
            try:
                await redis.set(f"run:{run_id}:cancel", "1", ex=3600)
            except RedisError:
                raise HTTPException(503, detail="取消信号暂时无法送达，请重试") from None
        else:
            raise Conflict("Run 已结束，不能取消")
    finally:
        await close_if_owned(redis, owned)
