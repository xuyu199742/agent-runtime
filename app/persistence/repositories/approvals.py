from datetime import UTC, datetime

from sqlalchemy import func, select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import Conflict, NotFound
from app.persistence.database import Approval, Run


class ApprovalRepository:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def ensure(
        self, run_id: str, call_id: str, name: str, title: str, description: str, risk: str
    ) -> Approval:
        await self.db.execute(
            insert(Approval)
            .values(
                run_id=run_id,
                tool_call_id=call_id,
                tool_name=name,
                title=title,
                description=description,
                risk=risk,
                status="PENDING",
            )
            .on_conflict_do_nothing(index_elements=["run_id", "tool_call_id"])
        )
        approval = await self.db.scalar(
            select(Approval).where(Approval.run_id == run_id, Approval.tool_call_id == call_id)
        )
        await self.db.commit()
        return approval

    async def get(self, approval_id: str) -> Approval | None:
        return await self.db.get(Approval, approval_id)

    async def for_run(self, run_id: str) -> list[Approval]:
        return list(
            (
                await self.db.scalars(
                    select(Approval)
                    .where(Approval.run_id == run_id)
                    .order_by(Approval.created_at, Approval.id)
                )
            ).all()
        )

    async def page(self, page: int, page_size: int, status: str | None):
        statement = select(Approval)
        if status is not None:
            statement = statement.where(Approval.status == status)
        total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (
            await self.db.scalars(
                statement.order_by(Approval.created_at.desc(), Approval.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), total or 0

    async def decision_for_run(self, run_id: str) -> bool | None:
        approval = await self.db.scalar(
            select(Approval)
            .where(Approval.run_id == run_id)
            .order_by(Approval.created_at.desc(), Approval.id.desc())
            .limit(1)
        )
        if approval is None or approval.status == "PENDING":
            return None
        return approval.status == "APPROVED"

    async def decide(self, approval_id: str, actor_id: str, approve: bool) -> Approval:
        approval = await self.db.scalar(
            select(Approval).where(Approval.id == approval_id).with_for_update()
        )
        if approval is None:
            raise NotFound("Approval 不存在")
        run = await self.db.get(Run, approval.run_id, with_for_update=True)
        if approval.status != "PENDING" or run.status != "WAITING":
            raise Conflict("Approval 已处理或 Run 不在等待状态")
        approval.status = "APPROVED" if approve else "REJECTED"
        approval.decided_by = actor_id
        approval.decided_at = datetime.now(UTC)
        await self.db.flush()
        remaining = await self.db.scalar(
            select(func.count())
            .select_from(Approval)
            .where(Approval.run_id == approval.run_id, Approval.status == "PENDING")
        )
        if remaining == 0:
            run.status = "PENDING"
        await self.db.commit()
        return approval

    async def cancel_waiting(self, run_id: str) -> bool:
        run = await self.db.get(Run, run_id, with_for_update=True)
        if run is None or run.status != "WAITING":
            return False
        run.status = "CANCELLED"
        run.completed_at = datetime.now(UTC)
        await self.db.execute(
            update(Approval)
            .where(Approval.run_id == run_id, Approval.status == "PENDING")
            .values(status="CANCELLED", decided_at=datetime.now(UTC))
        )
        await self.db.commit()
        return True
