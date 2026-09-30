from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.auth import Principal
from app.transport.http.common import Dashboard
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/dashboard", tags=["admin-dashboard"])
Viewer = Annotated[Principal, Depends(require("dashboard:view"))]


@router.get("")
async def overview(_user: Viewer, dashboard: Dashboard):
    return await dashboard.overview()
