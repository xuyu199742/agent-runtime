from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.auth import Principal
from app.transport.http.common import Artifacts, Conversation
from app.transport.http.v1.artifact_views import artifact_page
from app.transport.http.v1.dependencies import require
from app.transport.schemas.client import AgentSummary, MessageOut

router = APIRouter(prefix="/api/v1/admin/conversations", tags=["admin-conversations"])
Viewer = Annotated[Principal, Depends(require("conversation:view"))]


def summary(session, agent_name, last_message=None):
    return {
        "id": session.id,
        "title": session.title,
        "user_id": session.user_id,
        "agent": AgentSummary(id=session.agent_id, name=agent_name),
        "last_message": last_message,
        "last_active_at": session.last_active_at,
        "created_at": session.created_at,
        "archived_at": session.archived_at,
    }


@router.get("")
async def list_conversations(
    _user: Viewer,
    conversation: Conversation,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    rows, total = await conversation.list_sessions(None, page, page_size)
    return {
        "items": [
            summary(session, agent_name, last_message) for session, agent_name, last_message in rows
        ],
        "page": page,
        "page_size": page_size,
        "total": total,
    }


@router.get("/{conversation_id}")
async def detail(conversation_id: str, _user: Viewer, conversation: Conversation):
    session = await conversation.admin_session(conversation_id)
    result = summary(session, await conversation.agent_name(session.agent_id))
    result["statistics"] = await conversation.admin_statistics(conversation_id)
    return result


@router.get("/{conversation_id}/messages", response_model=list[MessageOut])
async def messages(
    conversation_id: str,
    _user: Viewer,
    conversation: Conversation,
    before: str | None = None,
    limit: int = Query(default=30, ge=1, le=100),
):
    rows = await conversation.admin_messages(conversation_id, before, limit)
    return [
        MessageOut(id=row.id, role=row.role, content=row.content, created_at=row.created_at)
        for row in rows
    ]


@router.get("/{conversation_id}/artifacts")
async def artifacts_for_conversation(
    conversation_id: str,
    _user: Viewer,
    conversation: Conversation,
    artifacts: Artifacts,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    await conversation.admin_session(conversation_id)
    rows, total = await artifacts.conversation(conversation_id, page, page_size)
    return artifact_page(rows, total, page, page_size)
