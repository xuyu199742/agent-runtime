from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.application.auth import Principal
from app.transport.http.common import Audit
from app.transport.http.v1.dependencies import require

router = APIRouter(prefix="/api/v1/admin/audit-logs", tags=["admin-audit"])
Viewer = Annotated[Principal, Depends(require("audit:view"))]


@router.get("")
async def list_audit(
    _user: Viewer,
    audit: Audit,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
):
    rows, total = await audit.page(page, page_size)
    return {"items": rows, "page": page, "page_size": page_size, "total": total}
