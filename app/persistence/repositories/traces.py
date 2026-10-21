"""Run 内时间线索引；事实正文保存在各自实体中。"""

from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.context.errors import ContextLeaseLost, ContextStateMismatch
from app.execution.model_serialization import model_input_hash
from app.persistence.database import ModelExecution, Run, RunTraceEvent, ToolExecution, new_id
from app.runtime.budget import BudgetModelCallsExceeded, check_deadline

TRACE_TYPES = {
    "activity.updated",
    "run.started",
    "run.resumed",
    "run.waiting",
    "run.completed",
    "run.failed",
    "run.cancelled",
    "model.started",
    "model.completed",
    "model.failed",
    "context_summary.started",
    "context_summary.completed",
    "context_summary.failed",
    "tool.started",
    "tool.completed",
    "tool.failed",
    "approval.required",
    "approval.approved",
    "approval.rejected",
    "approval.cancelled",
    "artifact.created",
    "policy.denied",
    "budget.exceeded",
    "effect.prepared",
    "effect.dispatched",
    "effect.succeeded",
    "effect.failed",
    "effect.uncertain",
    "effect.reconciling",
    "effect.manual_required",
    "effect.reused",
    "effect.idempotency_conflict",
}
TRACE_FIELDS = {
    "step_id",
    "tool_call_id",
    "name",
    "code",
    "approval_id",
    "artifact_id",
    "actor_id",
    "reason_code",
    "effect_type",
    "dimension",
    "limit",
    "used",
    "deadline_at",
    "now",
}


def trace_event(
    run_id: str,
    sequence: int,
    kind: str,
    data: dict,
    *,
    attempt: int = 1,
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> RunTraceEvent:
    if kind not in TRACE_TYPES:
        raise ValueError(f"不支持的 Run 时间线事件：{kind}")
    return RunTraceEvent(
        run_id=run_id,
        sequence=sequence,
        event_type=kind,
        attempt=attempt,
        ref_type=ref_type,
        ref_id=ref_id,
        data={key: value for key, value in data.items() if key in TRACE_FIELDS},
    )


class ExecutionRecorder:
    """只追加调用方事务内的时间线行，不提交事务或发布 Redis。"""

    def __init__(self, db):
        self.db = db

    def append_control_locked(
        self,
        run: Run,
        kind: str,
        data: dict,
        *,
        ref_type: str | None = None,
        ref_id: str | None = None,
    ) -> None:
        """调用方先锁定 Run 行；同一事务分配序号并追加控制面事实。"""
        if kind not in TRACE_TYPES:
            raise ValueError(f"不支持的 Run 时间线事件：{kind}")
        run.trace_sequence += 1
        self.add_at_sequence(
            run.id, run.trace_sequence, kind, data, ref_type=ref_type, ref_id=ref_id
        )

    @staticmethod
    def _model_event(phase: str, action: str) -> str:
        prefix = "context_summary" if phase == "CONTEXT_SUMMARY" else "model"
        return f"{prefix}.{action}"

    async def owns_run(self, run_id: str, worker_id: str) -> bool:
        owned = await self.db.scalar(
            select(Run.id)
            .where(
                Run.id == run_id,
                Run.status == "RUNNING",
                Run.lease_owner == worker_id,
                Run.lease_until > func.now(),
            )
            .with_for_update()
        )
        return owned is not None

    async def completed_summary(
        self, run_id: str, worker_id: str, step_id: str, input_messages: list[dict]
    ) -> str | None:
        if not await self.owns_run(run_id, worker_id):
            raise ContextLeaseLost
        row = await self.db.scalar(
            select(ModelExecution)
            .where(
                ModelExecution.run_id == run_id,
                ModelExecution.step_id == step_id,
                ModelExecution.phase == "CONTEXT_SUMMARY",
                ModelExecution.status == "COMPLETED",
            )
            .order_by(ModelExecution.attempt.desc())
            .limit(1)
        )
        if row is None:
            return None
        if row.input_hash != model_input_hash(input_messages):
            raise ContextStateMismatch("Working Context 摘要输入不一致")
        content = (row.output_message or {}).get("content")
        if not isinstance(content, str):
            raise TypeError("Working Context 摘要结果缺失")
        return content

    async def append(
        self,
        run_id: str,
        kind: str,
        data: dict,
        *,
        worker_id: str,
        attempt: int = 1,
        ref_type: str | None = None,
        ref_id: str | None = None,
    ) -> int | None:
        if kind not in TRACE_TYPES:
            raise ValueError(f"不支持的 Run 时间线事件：{kind}")
        sequence = await self.db.scalar(
            update(Run)
            .where(
                Run.id == run_id,
                Run.status == "RUNNING",
                Run.lease_owner == worker_id,
                Run.lease_until > func.now(),
            )
            .values(trace_sequence=Run.trace_sequence + 1)
            .returning(Run.trace_sequence)
        )
        if sequence is None:
            return None
        self.add_at_sequence(
            run_id, sequence, kind, data, attempt=attempt, ref_type=ref_type, ref_id=ref_id
        )
        return sequence

    async def start_model(
        self,
        run_id: str,
        worker_id: str,
        *,
        step_id: str,
        phase: str,
        provider: str,
        model_name: str,
        input_messages: list[dict],
        budget=None,
    ) -> ModelExecution | None:
        if not await self.owns_run(run_id, worker_id):
            return None
        if budget is not None:
            run = await self.db.get(Run, run_id)
            check_deadline(run.created_at, budget.max_duration_seconds)
        previous = await self.db.scalar(
            select(ModelExecution)
            .where(ModelExecution.run_id == run_id, ModelExecution.step_id == step_id)
            .order_by(ModelExecution.attempt.desc())
            .limit(1)
            .with_for_update()
        )
        if budget is not None and phase == "AGENT" and previous is None:
            used = await self.db.scalar(
                select(func.count(func.distinct(ModelExecution.step_id))).where(
                    ModelExecution.run_id == run_id, ModelExecution.phase == "AGENT"
                )
            )
            if used >= budget.max_model_calls:
                raise BudgetModelCallsExceeded(budget.max_model_calls, used)
        if previous is not None and previous.status == "STARTED":
            previous.status = "ABANDONED"
            previous.error_code = "WORKER_LOST"
            previous.completed_at = datetime.now(UTC)
            if (
                await self.append(
                    run_id,
                    self._model_event(previous.phase, "failed"),
                    {"step_id": step_id, "code": "WORKER_LOST"},
                    worker_id=worker_id,
                    attempt=previous.attempt,
                    ref_type="model_execution",
                    ref_id=previous.id,
                )
                is None
            ):
                return None
        attempt = previous.attempt + 1 if previous is not None else 1
        row = ModelExecution(
            id=new_id(),
            run_id=run_id,
            step_id=step_id,
            attempt=attempt,
            phase=phase,
            provider=provider,
            model_name=model_name,
            input_hash=model_input_hash(input_messages),
            input_messages=input_messages,
            status="STARTED",
        )
        self.db.add(row)
        if (
            await self.append(
                run_id,
                self._model_event(phase, "started"),
                {"step_id": step_id},
                worker_id=worker_id,
                attempt=attempt,
                ref_type="model_execution",
                ref_id=row.id,
            )
            is None
        ):
            return None
        await self.db.flush()
        return row

    async def complete_model(self, execution_id: str, worker_id: str, output: dict) -> bool:
        row = await self.db.get(ModelExecution, execution_id)
        if row is None or not await self.owns_run(row.run_id, worker_id):
            return False
        row = await self.db.get(ModelExecution, execution_id, with_for_update=True)
        if row.status != "STARTED":
            return False
        row.status = "COMPLETED"
        row.output_message = {
            key: output[key] for key in ("role", "content", "tool_calls") if key in output
        }
        row.tool_calls = output.get("tool_calls") or []
        row.usage = output.get("usage") or {}
        row.finish_reason = output.get("finish_reason")
        row.completed_at = datetime.now(UTC)
        return (
            await self.append(
                row.run_id,
                self._model_event(row.phase, "completed"),
                {"step_id": row.step_id},
                worker_id=worker_id,
                attempt=row.attempt,
                ref_type="model_execution",
                ref_id=row.id,
            )
            is not None
        )

    async def fail_model(self, execution_id: str, worker_id: str, code: str) -> bool:
        row = await self.db.get(ModelExecution, execution_id)
        if row is None or not await self.owns_run(row.run_id, worker_id):
            return False
        row = await self.db.get(ModelExecution, execution_id, with_for_update=True)
        if row.status != "STARTED":
            return False
        row.status = "FAILED"
        row.error_code = code
        row.completed_at = datetime.now(UTC)
        return (
            await self.append(
                row.run_id,
                self._model_event(row.phase, "failed"),
                {"step_id": row.step_id, "code": code},
                worker_id=worker_id,
                attempt=row.attempt,
                ref_type="model_execution",
                ref_id=row.id,
            )
            is not None
        )

    def add_at_sequence(
        self,
        run_id: str,
        sequence: int,
        kind: str,
        data: dict,
        *,
        attempt: int = 1,
        ref_type: str | None = None,
        ref_id: str | None = None,
    ) -> None:
        event = trace_event(
            run_id, sequence, kind, data, attempt=attempt, ref_type=ref_type, ref_id=ref_id
        )
        self.db.add(event)


class TraceRepository:
    def __init__(self, db):
        self.db = db

    async def page(self, run_id: str, page: int, page_size: int):
        statement = select(RunTraceEvent).where(RunTraceEvent.run_id == run_id)
        total = await self.db.scalar(select(func.count()).select_from(statement.subquery()))
        rows = (
            await self.db.scalars(
                statement.order_by(RunTraceEvent.sequence)
                .offset((page - 1) * page_size)
                .limit(page_size)
            )
        ).all()
        return list(rows), total or 0

    async def timeline_page(self, run_id: str, page: int, page_size: int):
        rows, total = await self.page(run_id, page, page_size)
        model_ids = [row.ref_id for row in rows if row.ref_type == "model_execution" and row.ref_id]
        tool_ids = [row.ref_id for row in rows if row.ref_type == "tool_execution" and row.ref_id]
        models = (
            {
                row.id: row
                for row in await self.db.scalars(
                    select(ModelExecution).where(ModelExecution.id.in_(model_ids))
                )
            }
            if model_ids
            else {}
        )
        tools = (
            {
                row.id: row
                for row in await self.db.scalars(
                    select(ToolExecution).where(ToolExecution.id.in_(tool_ids))
                )
            }
            if tool_ids
            else {}
        )
        items = []
        for row in rows:
            fact = (
                models.get(row.ref_id)
                if row.ref_type == "model_execution"
                else tools.get(row.ref_id)
                if row.ref_type == "tool_execution"
                else None
            )
            duration = None
            if fact is not None and fact.completed_at is not None:
                duration = int((fact.completed_at - fact.started_at).total_seconds() * 1000)
            name = row.data.get("name") or row.data.get("code")
            items.append(
                {
                    "sequence": row.sequence,
                    "event_type": row.event_type,
                    "attempt": row.attempt,
                    "created_at": row.created_at,
                    "ref_type": row.ref_type,
                    "ref_id": row.ref_id,
                    "duration": duration,
                    "summary": f"{row.event_type}: {name}" if name else row.event_type,
                }
            )
        return items, total
