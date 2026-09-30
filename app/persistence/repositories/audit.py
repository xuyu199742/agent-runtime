from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import AuditLog


class AuditRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def record(
        self,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str | None,
        request_id: str | None,
        ip: str | None,
        before_snapshot: dict | None = None,
        after_snapshot: dict | None = None,
    ) -> None:
        self.db.add(
            AuditLog(
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                ip=ip,
                before_snapshot=before_snapshot,
                after_snapshot=after_snapshot,
            )
        )
        await self.db.commit()

    async def page(self, page: int, page_size: int):
        total = await self.db.scalar(select(func.count()).select_from(AuditLog))
        rows = (
            await self.db.scalars(
                select(AuditLog)
                .order_by(AuditLog.created_at.desc(), AuditLog.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), total or 0
