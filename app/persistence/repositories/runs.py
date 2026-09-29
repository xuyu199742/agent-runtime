from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.database import Message, Run, Session, new_id

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

    async def answer(self, message_id: str):
        return await self.db.get(Message, message_id)

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
        .values(status="COMPLETED", answer_message_id=answer_id, lease_owner=None, lease_until=None)
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
        .values(status=status, error_code=code, lease_owner=None, lease_until=None)
        .returning(Run.id)
    )
    updated = await db.scalar(statement)
    await db.commit()
    return updated is not None


async def cancel_pending(db: AsyncSession, run_id: str) -> bool:
    statement = (
        update(Run)
        .where(Run.id == run_id, Run.status == "PENDING")
        .values(status="CANCELLED")
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
