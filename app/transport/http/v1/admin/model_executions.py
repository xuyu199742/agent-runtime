"""管理员按需读取单次模型调用的白名单正文。"""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.application.auth import Principal
from app.transport.http.common import Runs
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/model-executions", tags=["admin-model-executions"])
Viewer = Annotated[Principal, Depends(require("run:view"))]


@router.get("/{execution_id}")
async def detail(execution_id: str, _user: Viewer, runs: Runs):
    return await runs.model_execution(execution_id)
