from datetime import UTC, datetime, timedelta

from sqlalchemy import and_, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.infrastructure.database import Message, Run, Session, new_id

LEASE_SECONDS = 45


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
    statement = (
        update(Run)
        .where(Run.id == run_id, Run.status == "RUNNING", Run.lease_owner == worker_id)
        .values(lease_until=datetime.now(UTC) + timedelta(seconds=LEASE_SECONDS))
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
        .where(Run.id == run_id, Run.status == "RUNNING", Run.lease_owner == worker_id)
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
    if status not in {"FAILED", "CANCELLED", "INTERRUPTED"}:
        raise ValueError("无效的终态")
    statement = (
        update(Run)
        .where(Run.id == run_id, Run.status == "RUNNING", Run.lease_owner == worker_id)
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


async def pending_run_ids(db: AsyncSession, limit: int = 100) -> list[str]:
    return list(
        (await db.scalars(select(Run.id).where(Run.status == "PENDING").limit(limit))).all()
    )
