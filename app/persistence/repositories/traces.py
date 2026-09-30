"""只持久化生命周期事件，不保存模型 token 或最终回答。"""

from sqlalchemy import func, select

from app.persistence.database import RunTraceEvent

TRACE_TYPES = {
    "run.started",
    "run.resumed",
    "run.waiting",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "model.started",
    "model.completed",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "approval.required",
    "artifact.created",
}
TRACE_FIELDS = {"step_id", "tool_call_id", "name", "code", "approval_id", "artifact_id"}


def trace_event(run_id: str, kind: str, data: dict) -> RunTraceEvent | None:
    if kind not in TRACE_TYPES:
        return None
    return RunTraceEvent(
        run_id=run_id,
        event_type=kind,
        data={key: value for key, value in data.items() if key in TRACE_FIELDS},
    )


class TraceRepository:
    def __init__(self, db):
        self.db = db

    async def record(self, run_id: str, kind: str, data: dict) -> None:
        event = trace_event(run_id, kind, data)
        if event is not None:
            self.db.add(event)
            await self.db.commit()

    async def page(self, run_id: str, page: int, page_size: int):
        statement = select(RunTraceEvent).where(RunTraceEvent.run_id == run_id)
        total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (
            await self.db.scalars(
                statement.order_by(RunTraceEvent.id).offset((page - 1) * page_size).limit(page_size)
            )
        ).all()
        return list(rows), total or 0
