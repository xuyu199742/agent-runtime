from fastapi import Request

from app.application.auth import Principal
from app.transport.http.common import Audit


async def record_action(
    audit: Audit,
    request: Request,
    user: Principal,
    action: str,
    resource_type: str,
    resource_id: str | None,
    after: dict | None = None,
):
    await audit.record(
        user.id,
        action,
        resource_type,
        resource_id,
        getattr(request.state, "request_id", None),
        request.client.host if request.client else None,
        after_snapshot=after,
    )
