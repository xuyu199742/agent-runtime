import structlog
from fastapi import APIRouter, HTTPException, Request
from redis.exceptions import RedisError

from app.application.chat import create_session, submit_message
from app.config import get_settings
from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.run_queue import RunQueue
from app.persistence.database import Session
from app.transport.http.common import Db
from app.transport.schemas import MessageAccepted, MessageIn, SessionIn, SessionOut

log = structlog.get_logger()

router = APIRouter()


@router.post("/api/sessions", response_model=SessionOut, status_code=201)
async def add_session(body: SessionIn, db: Db):
    return await create_session(db, body.agent_id, get_settings().dev_user_id)


@router.get("/api/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, db: Db):
    session = await db.get(Session, session_id)
    if session is None or session.user_id != get_settings().dev_user_id:
        raise HTTPException(404, detail="Session 不存在")
    return session


@router.post("/api/sessions/{session_id}/messages", response_model=MessageAccepted, status_code=202)
async def add_message(session_id: str, body: MessageIn, db: Db, request: Request):
    accepted = await submit_message(
        db, session_id, get_settings().dev_user_id, body.client_message_id, body.content
    )
    redis, owned = redis_for_request(request)
    try:
        await RunQueue(redis).enqueue(accepted.run_id)
    except RedisError:
        log.warning("Run 入队失败，等待 Worker 补投", run_id=accepted.run_id)
    finally:
        await close_if_owned(redis, owned)
    return accepted
