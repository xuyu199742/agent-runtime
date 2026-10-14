"""上下文快照的读取和租约围栏提交。摘要与快照在同一个事务里写入。"""

from datetime import UTC, datetime

from sqlalchemy import select, tuple_
from sqlalchemy.exc import IntegrityError

from app.context.planner import ContextMessage, PlannedContext, SummaryView
from app.context.snapshot import context_content_hash
from app.persistence.database import (
    ConversationSummary,
    Message,
    Run,
    RunContextSnapshot,
    RunTraceEvent,
    Session,
    new_id,
)


class ContextCommitLost(Exception):
    pass


async def context_snapshot(db, run_id: str) -> RunContextSnapshot | None:
    return await db.scalar(select(RunContextSnapshot).where(RunContextSnapshot.run_id == run_id))


async def execution_observed(db, run: Run) -> bool:
    if run.waiting_at is not None:
        return True
    found = await db.scalar(
        select(RunTraceEvent.id).where(
            RunTraceEvent.run_id == run.id,
            RunTraceEvent.event_type.in_(("model.started", "run.started")),
        )
    )
    return found is not None


async def latest_summary(db, session_id: str) -> ConversationSummary | None:
    return await db.scalar(
        select(ConversationSummary)
        .where(ConversationSummary.session_id == session_id)
        .order_by(ConversationSummary.revision.desc())
        .limit(1)
    )


async def messages_for_planning(
    db, session_id: str, current: Message, summary: ConversationSummary | None
) -> list[ContextMessage]:
    conditions = [
        Message.session_id == session_id,
        tuple_(Message.created_at, Message.id) <= tuple_(current.created_at, current.id),
    ]
    if summary is not None:
        through = await db.get(Message, summary.through_message_id)
        conditions.append(
            tuple_(Message.created_at, Message.id) > tuple_(through.created_at, through.id)
        )
    rows = (
        await db.scalars(
            select(Message).where(*conditions).order_by(Message.created_at, Message.id)
        )
    ).all()
    return [_message(row) for row in rows]


async def summary_view(db, row: ConversationSummary) -> SummaryView:
    through = await db.get(Message, row.through_message_id)
    return SummaryView(
        id=row.id,
        revision=row.revision,
        text=row.summary,
        token_estimate=row.token_estimate,
        from_message_id=row.from_message_id,
        through_message_id=row.through_message_id,
        through_created_at=through.created_at,
        source_message_count=row.source_message_count,
        prompt_hash=row.prompt_hash,
    )


async def load_snapshot_messages(
    db, snapshot: RunContextSnapshot
) -> tuple[str | None, list[ContextMessage]]:
    summary_text = None
    if snapshot.summary_id is not None:
        summary = await db.get(ConversationSummary, snapshot.summary_id)
        if summary is None:
            raise ValueError("快照引用的摘要不存在")
        summary_text = summary.summary
    ids = list(snapshot.message_ids)
    if not ids:
        messages: list[ContextMessage] = []
    else:
        rows = {row.id: row for row in await db.scalars(select(Message).where(Message.id.in_(ids)))}
        if len(rows) != len(ids):
            raise ValueError("快照引用的消息不存在")
        messages = [_message(rows[message_id]) for message_id in ids]
    digest = context_content_hash(
        snapshot.summary_id, summary_text, messages, dict(snapshot.budget or {})
    )
    if digest != snapshot.content_hash:
        raise ValueError("上下文快照内容与首次执行不一致")
    return summary_text, messages


async def commit_planned_context(
    db_factory,
    run_id: str,
    worker_id: str | None,
    planned: PlannedContext,
    *,
    provider: str,
    model_name: str,
    context_budget: dict,
) -> None:
    """持有租约时插入摘要和快照。失败则回滚，不留下半份摘要。"""
    async with db_factory() as db:
        run = await db.scalar(select(Run).where(Run.id == run_id).with_for_update())
        now = datetime.now(UTC)
        owns = (
            run is not None
            and worker_id is not None
            and run.status == "RUNNING"
            and run.lease_owner == worker_id
            and run.lease_until is not None
            and run.lease_until > now
        )
        if not owns:
            await db.rollback()
            raise ContextCommitLost
        await db.execute(select(Session.id).where(Session.id == run.session_id).with_for_update())
        existing = await context_snapshot(db, run_id)
        if existing is not None:
            await db.rollback()
            return
        latest = await latest_summary(db, run.session_id)
        latest_revision = latest.revision if latest is not None else None
        if latest_revision != planned.expected_revision:
            await db.rollback()
            raise ContextCommitLost
        summary_id = planned.existing_summary_id
        if planned.summary_insert is not None:
            inserted = ConversationSummary(
                id=new_id(),
                session_id=run.session_id,
                revision=(planned.expected_revision or 0) + 1,
                from_message_id=planned.summary_insert.from_message_id,
                through_message_id=planned.summary_insert.through_message_id,
                summary=planned.summary_insert.summary,
                token_estimate=planned.summary_insert.token_estimate,
                source_message_count=planned.summary_insert.source_message_count,
                model_provider=provider,
                model_name=model_name,
                prompt_hash=planned.summary_insert.prompt_hash,
            )
            db.add(inserted)
            await db.flush()
            summary_id = inserted.id
        budget = {**context_budget, "estimated_tokens": planned.estimated_tokens}
        found = {
            row.id: row
            for row in await db.scalars(select(Message).where(Message.id.in_(planned.message_ids)))
        }
        if len(found) != len(planned.message_ids):
            await db.rollback()
            raise ContextCommitLost
        messages = [_message(found[message_id]) for message_id in planned.message_ids]
        db.add(
            RunContextSnapshot(
                id=new_id(),
                run_id=run_id,
                summary_id=summary_id,
                message_ids=list(planned.message_ids),
                estimated_tokens=planned.estimated_tokens,
                budget=budget,
                content_hash=context_content_hash(
                    summary_id, planned.summary_text, messages, budget
                ),
            )
        )
        try:
            await db.commit()
        except IntegrityError as exc:
            await db.rollback()
            raise ContextCommitLost from exc


def _message(row: Message) -> ContextMessage:
    return ContextMessage(id=row.id, role=row.role, content=row.content, created_at=row.created_at)
