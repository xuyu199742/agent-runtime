from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.errors import Conflict
from app.persistence.database import (
    AgentDefinition,
    ExecutionSpec,
    Message,
    Run,
    Session,
    ToolExecution,
    new_id,
)

LEASE_SECONDS = 45


class RunRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def visible(self, run_id: str, user_id: str):
        return await self.db.scalar(
            select(Run)
            .join(Session, Run.session_id == Session.id)
            .where(Run.id == run_id, Session.user_id == user_id)
            .execution_options(populate_existing=True)
        )

    async def get(self, run_id: str):
        return await self.db.get(Run, run_id)

    async def execution_spec(self, spec_id: str):
        return await self.db.get(ExecutionSpec, spec_id)

    async def tool_executions(self, run_id: str):
        return list(
            (
                await self.db.scalars(
                    select(ToolExecution)
                    .where(ToolExecution.run_id == run_id)
                    .order_by(ToolExecution.started_at, ToolExecution.id)
                )
            ).all()
        )

    async def retry(self, run_id: str):
        original = await self.db.get(Run, run_id)
        if original is None:
            return None
        await self.db.execute(
            select(Session.id).where(Session.id == original.session_id).with_for_update()
        )
        if original.status != "FAILED":
            raise Conflict("只有失败的 Run 可以重试")
        active = await self.db.scalar(
            select(Run.id)
            .where(
                Run.session_id == original.session_id,
                Run.status.in_(["PENDING", "RUNNING", "WAITING"]),
            )
            .limit(1)
        )
        if active is not None:
            raise Conflict("会话中已有执行中的 Run")
        retry = Run(
            session_id=original.session_id,
            message_id=original.message_id,
            status="PENDING",
            execution_spec_id=original.execution_spec_id,
            runtime_version=original.runtime_version,
            parent_run_id=original.id,
            attempt=original.attempt + 1,
            origin="RETRY",
        )
        self.db.add(retry)
        await self.db.commit()
        await self.db.refresh(retry)
        return retry

    async def answer(self, message_id: str):
        return await self.db.get(Message, message_id)

    async def list_runs(
        self,
        page: int,
        page_size: int,
        user_id: str | None = None,
        status: str | None = None,
        agent_id: str | None = None,
        worker_id: str | None = None,
        error_code: str | None = None,
    ):
        statement = (
            select(Run, Session.user_id, AgentDefinition.id, AgentDefinition.name)
            .join(Session, Run.session_id == Session.id)
            .join(AgentDefinition, Session.agent_id == AgentDefinition.id)
        )
        if user_id is not None:
            statement = statement.where(Session.user_id == user_id)
        if status is not None:
            statement = statement.where(Run.status == status)
        if agent_id is not None:
            statement = statement.where(AgentDefinition.id == agent_id)
        if worker_id is not None:
            statement = statement.where(Run.lease_owner == worker_id)
        if error_code is not None:
            statement = statement.where(Run.error_code == error_code)
        total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (
            await self.db.execute(
                statement.order_by(Run.created_at.desc(), Run.id.desc())
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), total or 0

    async def admin_context(self, run_id: str):
        return (
            await self.db.execute(
                select(Session.user_id, AgentDefinition.id, AgentDefinition.name)
                .join(AgentDefinition, AgentDefinition.id == Session.agent_id)
                .join(Run, Run.session_id == Session.id)
                .where(Run.id == run_id)
            )
        ).first()

    async def cancel_pending(self, run_id: str) -> bool:
        return await cancel_pending(self.db, run_id)

    async def status(self, run_id: str) -> str | None:
        await self.release_read()
        return await self.db.scalar(select(Run.status).where(Run.id == run_id))

    async def release_read(self) -> None:
        await self.db.rollback()  # SSE 等待期间不持有数据库只读事务。


async def claim_run(db: AsyncSession, run_id: str, worker_id: str) -> bool:
    now = datetime.now(UTC)
    statement = (
        update(Run)
        .where(
            Run.id == run_id,
            or_(
                Run.status == "PENDING",
                and_(Run.status == "RUNNING", Run.lease_until < now),
            ),
        )
        .values(
            status="RUNNING",
            lease_owner=worker_id,
            lease_until=now + timedelta(seconds=LEASE_SECONDS),
            started_at=func.coalesce(Run.started_at, now),
        )
        .returning(Run.id)
    )
    claimed = await db.scalar(statement)
    await db.commit()
    return claimed is not None


async def extend_lease(db: AsyncSession, run_id: str, worker_id: str) -> bool:
    now = datetime.now(UTC)
    statement = (
        update(Run)
        .where(
            Run.id == run_id,
            Run.status == "RUNNING",
            Run.lease_owner == worker_id,
            Run.lease_until > now,
        )
        .values(lease_until=now + timedelta(seconds=LEASE_SECONDS))
        .returning(Run.id)
    )
    updated = await db.scalar(statement)
    await db.commit()
    return updated is not None


async def finish_run(db: AsyncSession, run_id: str, worker_id: str, answer: str) -> bool:
    run = await db.get(Run, run_id)
    if run is None:
        return False
    session = await db.get(Session, run.session_id)
    session.last_active_at = datetime.now(UTC)
    answer_id = new_id()
    db.add(
        Message(
            id=answer_id,
            session_id=run.session_id,
            user_id=session.user_id,
            role="assistant",
            content=answer,
        )
    )
    await db.flush()
    statement = (
        update(Run)
        .where(
            Run.id == run_id,
            Run.status == "RUNNING",
            Run.lease_owner == worker_id,
            Run.lease_until > datetime.now(UTC),
        )
        .values(
            status="COMPLETED",
            answer_message_id=answer_id,
            lease_owner=None,
            lease_until=None,
            completed_at=datetime.now(UTC),
        )
        .returning(Run.id)
    )
    updated = await db.scalar(statement)
    if updated is None:
        await db.rollback()
        return False
    await db.commit()
    return True


async def end_run(
    db: AsyncSession, run_id: str, worker_id: str, status: str, code: str | None = None
) -> bool:
    if status not in {"FAILED", "CANCELLED"}:
        raise ValueError("无效的终态")
    statement = (
        update(Run)
        .where(
            Run.id == run_id,
            Run.status == "RUNNING",
            Run.lease_owner == worker_id,
            Run.lease_until > datetime.now(UTC),
        )
        .values(
            status=status,
            error_code=code,
            lease_owner=None,
            lease_until=None,
            completed_at=datetime.now(UTC),
        )
        .returning(Run.id)
    )
    updated = await db.scalar(statement)
    await db.commit()
    return updated is not None


async def cancel_pending(db: AsyncSession, run_id: str) -> bool:
    statement = (
        update(Run)
        .where(Run.id == run_id, Run.status == "PENDING")
        .values(status="CANCELLED", completed_at=datetime.now(UTC))
        .returning(Run.id)
    )
    updated = await db.scalar(statement)
    await db.commit()
    return updated is not None


async def pending_run_ids(
    db: AsyncSession, limit: int = 100, after: str | None = None
) -> list[str]:
    statement = select(Run.id).where(Run.status == "PENDING")
    if after is not None:
        statement = statement.where(Run.id > after)
    return list((await db.scalars(statement.order_by(Run.id).limit(limit))).all())


async def expired_checkpoint_run_ids(
    db: AsyncSession, retention_hours: int, limit: int = 100
) -> list[str]:
    cutoff = datetime.now(UTC) - timedelta(hours=retention_hours)
    return list(
        (
            await db.scalars(
                select(Run.id)
                .where(
                    Run.status.in_(["COMPLETED", "FAILED", "CANCELLED"]),
                    Run.updated_at < cutoff,
                    Run.checkpoint_pruned_at.is_(None),
                )
                .order_by(Run.updated_at)
                .limit(limit)
            )
        ).all()
    )


async def mark_checkpoint_pruned(db: AsyncSession, run_id: str) -> None:
    await db.execute(
        update(Run)
        .where(Run.id == run_id)
        .values(checkpoint_pruned_at=datetime.now(UTC), updated_at=Run.updated_at)
    )
    await db.commit()
