import structlog
from fastapi import APIRouter, HTTPException
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy.ext.asyncio import AsyncSession

from app.application.runs import cancel_pending
from app.config import get_settings
from app.infrastructure.database import Message, Run, Session
from app.infrastructure.events import EventStore
from app.transport.http.common import Db
from app.transport.schemas import RunOut

log = structlog.get_logger()

router = APIRouter()


async def visible_run(db: AsyncSession, run_id: str) -> Run:
    run = await db.get(Run, run_id)
    if run is None:
        raise HTTPException(404, detail="Run 不存在")
    session = await db.get(Session, run.session_id)
    if session.user_id != get_settings().dev_user_id:
        raise HTTPException(404, detail="Run 不存在")
    return run


@router.get("/api/runs/{run_id}", response_model=RunOut)
async def get_run(run_id: str, db: Db):
    run = await visible_run(db, run_id)
    result = RunOut.model_validate(run)
    if run.answer_message_id:
        answer = await db.get(Message, run.answer_message_id)
        result.answer = answer.content if answer else None
    return result


@router.post("/api/runs/{run_id}/cancel", response_model=RunOut)
async def cancel_run(run_id: str, db: Db):
    run = await visible_run(db, run_id)
    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        if run.status == "PENDING" and await cancel_pending(db, run_id):
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
        await redis.aclose()
    await db.refresh(run)
    return await get_run(run_id, db)
