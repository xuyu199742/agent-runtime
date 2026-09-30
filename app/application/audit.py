from app.persistence.repositories.audit import AuditRepository


class AuditService:
    def __init__(self, repository: AuditRepository) -> None:
        self.repository = repository

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
        await self.repository.record(
            actor_id,
            action,
            resource_type,
            resource_id,
            request_id,
            ip,
            before_snapshot,
            after_snapshot,
        )

    async def page(self, page: int, page_size: int):
        return await self.repository.page(page, page_size)
