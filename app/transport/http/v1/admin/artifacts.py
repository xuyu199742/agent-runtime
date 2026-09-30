from typing import Annotated

from fastapi import APIRouter, Depends, Query
from fastapi.responses import FileResponse

from app.application.auth import Principal
from app.transport.http.common import Artifacts
from app.transport.http.v1.artifact_views import artifact_out, artifact_page
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/artifacts", tags=["admin-artifacts"])
Viewer = Annotated[Principal, Depends(require("artifact:view"))]


@router.get("")
async def list_artifacts(
    _user: Viewer,
    artifacts: Artifacts,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    user_id: str | None = None,
):
    rows, total = await artifacts.admin_page(page, page_size, user_id)
    return artifact_page(rows, total, page, page_size)


@router.get("/{artifact_id}")
async def detail(artifact_id: str, _user: Viewer, artifacts: Artifacts):
    return artifact_out(await artifacts.get(artifact_id))


@router.get("/{artifact_id}/download")
async def download(artifact_id: str, _user: Viewer, artifacts: Artifacts):
    artifact = await artifacts.get(artifact_id)
    return FileResponse(
        artifacts.file_path(artifact), media_type=artifact.mime_type, filename=artifact.name
    )
