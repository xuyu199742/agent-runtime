from fastapi import APIRouter, Query
from fastapi.responses import FileResponse

from app.transport.http.common import Artifacts, Conversation
from app.transport.http.v1.artifact_views import artifact_out, artifact_page
from app.transport.http.v1.dependencies import CurrentUser

router = APIRouter(prefix="/api/v1/client", tags=["client-artifacts"])


@router.get("/conversations/{conversation_id}/artifacts")
async def conversation_artifacts(
    conversation_id: str,
    user: CurrentUser,
    conversation: Conversation,
    artifacts: Artifacts,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    await conversation.get_session(conversation_id, user.id)
    rows, total = await artifacts.conversation(conversation_id, page, page_size)
    return artifact_page(rows, total, page, page_size)


@router.get("/artifacts/{artifact_id}")
async def detail(artifact_id: str, user: CurrentUser, artifacts: Artifacts):
    return artifact_out(await artifacts.visible(artifact_id, user.id))


@router.get("/artifacts/{artifact_id}/download")
async def download(artifact_id: str, user: CurrentUser, artifacts: Artifacts):
    artifact = await artifacts.visible(artifact_id, user.id)
    return FileResponse(
        artifacts.file_path(artifact), media_type=artifact.mime_type, filename=artifact.name
    )
