import structlog
from fastapi import APIRouter, Request
from redis.exceptions import RedisError

from app.config import get_settings
from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.run_queue import RunQueue
from app.transport.http.common import Conversation
from app.transport.schemas import MessageAccepted, MessageIn, SessionIn, SessionOut

log = structlog.get_logger()

router = APIRouter()


@router.post("/api/sessions", response_model=SessionOut, status_code=201)
async def add_session(body: SessionIn, conversation: Conversation):
    return await conversation.create_session(body.agent_id, get_settings().dev_user_id)


@router.get("/api/sessions/{session_id}", response_model=SessionOut)
async def get_session(session_id: str, conversation: Conversation):
    return await conversation.get_session(session_id, get_settings().dev_user_id)


@router.post("/api/sessions/{session_id}/messages", response_model=MessageAccepted, status_code=202)
async def add_message(
    session_id: str, body: MessageIn, conversation: Conversation, request: Request
):
    accepted = await conversation.submit_message(
        session_id, get_settings().dev_user_id, body.client_message_id, body.content
    )
    redis, owned = redis_for_request(request)
    try:
        await RunQueue(redis).enqueue(accepted.run_id)
    except RedisError:
        log.warning("Run 入队失败，等待 Worker 补投", run_id=accepted.run_id)
    finally:
        await close_if_owned(redis, owned)
    return accepted
