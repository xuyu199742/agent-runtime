import structlog
from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field
from redis.exceptions import RedisError

from app.messaging.client import close_if_owned, redis_for_request
from app.messaging.run_queue import RunQueue
from app.transport.http.common import Conversation
from app.transport.http.v1.dependencies import CurrentUser
from app.transport.schemas.client import AgentSummary, ConversationOut, MessageOut, Page
from app.transport.schemas.legacy import MessageIn, SessionIn

log = structlog.get_logger()
router = APIRouter(prefix="/api/v1/client/conversations", tags=["client-conversations"])


class TitleIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)


def conversation_out(session, agent_name: str, last_message=None):
    return ConversationOut(
        id=session.id,
        title=session.title,
        agent=AgentSummary(id=session.agent_id, name=agent_name),
        last_message=last_message,
        last_active_at=session.last_active_at,
        created_at=session.created_at,
    )


@router.post("", status_code=201)
async def create(body: SessionIn, user: CurrentUser, conversation: Conversation):
    session = await conversation.create_session(body.agent_id, user.id)
    return conversation_out(session, await conversation.agent_name(body.agent_id))


@router.get("", response_model=Page)
async def list_conversations(
    user: CurrentUser,
    conversation: Conversation,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    rows, total = await conversation.list_sessions(user.id, page, page_size)
    return Page(
        items=[
            conversation_out(session, agent_name, last_message)
            for session, agent_name, last_message in rows
        ],
        page=page,
        page_size=page_size,
        total=total,
    )


@router.get("/{conversation_id}")
async def detail(conversation_id: str, user: CurrentUser, conversation: Conversation):
    session = await conversation.get_session(conversation_id, user.id)
    return conversation_out(session, await conversation.agent_name(session.agent_id))


@router.patch("/{conversation_id}")
async def update(
    conversation_id: str, body: TitleIn, user: CurrentUser, conversation: Conversation
):
    session = await conversation.update_title(conversation_id, user.id, body.title)
    return conversation_out(session, await conversation.agent_name(session.agent_id))


@router.delete("/{conversation_id}", status_code=204)
async def archive(conversation_id: str, user: CurrentUser, conversation: Conversation):
    await conversation.archive(conversation_id, user.id)


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def messages(
    conversation_id: str,
    user: CurrentUser,
    conversation: Conversation,
    before: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
):
    rows = await conversation.messages(conversation_id, user.id, before, limit)
    return [
        MessageOut.model_validate(
            {"id": row.id, "role": row.role, "content": row.content, "created_at": row.created_at}
        )
        for row in rows
    ]


@router.post("/{conversation_id}/messages", status_code=202)
async def send_message(
    conversation_id: str,
    body: MessageIn,
    user: CurrentUser,
    conversation: Conversation,
    request: Request,
):
    accepted = await conversation.submit_message(
        conversation_id, user.id, body.client_message_id, body.content
    )
    redis, owned = redis_for_request(request)
    try:
        await RunQueue(redis).enqueue(accepted.run_id)
    except RedisError:
        log.warning("Run 入队失败，等待 Worker 补投", run_id=accepted.run_id)
    finally:
        await close_if_owned(redis, owned)
    return {
        "message": {"id": accepted.message_id},
        "run": {"id": accepted.run_id, "status": "PENDING"},
    }
