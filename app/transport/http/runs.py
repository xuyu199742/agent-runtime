import structlog
from fastapi import APIRouter, HTTPException, Request
from redis.exceptions import RedisError

from app.config import get_settings
from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.events import EventStore
from app.transport.http.common import Runs
from app.transport.schemas import RunOut

log = structlog.get_logger()

router = APIRouter()


@router.get("/api/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, runs: Runs):
    run, answer = await runs.detail(run_id, get_settings().dev_user_id)
    result = RunOut.model_validate(run)
    result.answer = answer
    return result


@router.post("/api/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: str, runs: Runs, request: Request):
    run = await runs.visible(run_id, get_settings().dev_user_id)
    redis, owned = redis_for_request(request)
    try:
        if run.status == "PENDING" and await runs.cancel_pending(run_id):
            try:
                await EventStore(redis).publish(run_id, "run.cancelled", {})
            except RedisError:
                log.warning("取消事件投递失败，可从 Run 状态恢复", run_id=run_id)
        elif run.status == "RUNNING":
            try:
                await redis.set(f"run:{run_id}:cancel", "1", ex=3600)
            except RedisError:
                raise HTTPException(503, detail="取消信号暂时无法送达，请重试") from None
    finally:
        await close_if_owned(redis, owned)
    return await get_run(run_id, runs)
