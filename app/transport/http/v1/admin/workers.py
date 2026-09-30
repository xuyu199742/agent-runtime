from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.auth import Principal
from app.transport.http.common import Workers
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/workers", tags=["admin-workers"])
Viewer = Annotated[Principal, Depends(require("worker:view"))]


@router.get("")
async def list_workers(_user: Viewer, workers: Workers):
    return await workers.list()


@router.get("/{worker_id}")
async def detail(worker_id: str, _user: Viewer, workers: Workers):
    return await workers.detail(worker_id)
