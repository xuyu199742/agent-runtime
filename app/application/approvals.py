from app.domain.errors import NotFound
from app.persistence.repositories.approvals import ApprovalRepository


class ApprovalService:
    def __init__(self, repository: ApprovalRepository):
        self.repository = repository

    async def get(self, approval_id: str):
        approval = await self.repository.get(approval_id)
        if approval is None:
            raise NotFound("Approval 不存在")
        return approval

    async def for_run(self, run_id: str):
        return await self.repository.for_run(run_id)

    async def page(self, page: int, page_size: int, status: str | None):
        return await self.repository.page(page, page_size, status)

    async def decide(self, approval_id: str, actor_id: str, approve: bool):
        return await self.repository.decide(approval_id, actor_id, approve)
