"""Tool 调用事实写入 PostgreSQL；唯一键为 Run 与模型生成的 Tool Call ID。"""

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert

from app.context.errors import ContextLeaseLost
from app.persistence.database import Run, ToolExecution
from app.persistence.repositories.activity import append_snapshot, latest_snapshot, preview
from app.persistence.repositories.traces import ExecutionRecorder
from app.runtime.budget import BudgetToolCallsExceeded, check_deadline


class ToolExecutionStore:
    def __init__(self, session_factory, worker_id: str, budget=None):
        self.session_factory = session_factory
        self.worker_id = worker_id
        self.budget = budget
        self.skill_metadata = {}

    async def start(
        self,
        run_id: str,
        call_id: str,
        name: str,
        effect_type: str,
        args_hash: str,
        *,
        arguments=None,
        skill_config=None,
    ) -> ToolExecution:
        async with self.session_factory() as db:
            recorder = ExecutionRecorder(db)
            if not await recorder.owns_run(run_id, self.worker_id):
                raise ContextLeaseLost
            row = await db.scalar(
                select(ToolExecution)
                .where(ToolExecution.run_id == run_id, ToolExecution.tool_call_id == call_id)
                .with_for_update()
            )
            if self.budget is not None:
                run = await db.get(Run, run_id)
                check_deadline(run.created_at, self.budget.max_duration_seconds)
            if row is None:
                if self.budget is not None:
                    used = await db.scalar(
                        select(func.count(ToolExecution.id)).where(ToolExecution.run_id == run_id)
                    )
                    if used >= self.budget.max_tool_calls:
                        raise BudgetToolCallsExceeded(self.budget.max_tool_calls, used)
                await db.execute(
                    insert(ToolExecution)
                    .values(
                        run_id=run_id,
                        tool_call_id=call_id,
                        tool_name=name,
                        effect_type=effect_type,
                        idempotency_key=f"{run_id}:{call_id}",
                        args_hash=args_hash,
                        status="STARTED",
                        attempt=0,
                    )
                    .on_conflict_do_nothing(index_elements=["run_id", "tool_call_id"])
                )
                row = await db.scalar(
                    select(ToolExecution)
                    .where(ToolExecution.run_id == run_id, ToolExecution.tool_call_id == call_id)
                    .with_for_update()
                )
            if row.tool_name != name or row.args_hash != args_hash:
                raise ValueError("Tool Call ID 与既有参数不一致")
            if row.status != "COMPLETED":
                row.attempt += 1
                row.status = "STARTED"
                row.started_at = datetime.now(UTC)
                row.completed_at = None
                if (
                    await recorder.append(
                        run_id,
                        "tool.started",
                        {"name": name, "tool_call_id": call_id},
                        worker_id=self.worker_id,
                        attempt=row.attempt,
                        ref_type="tool_execution",
                        ref_id=row.id,
                    )
                    is None
                ):
                    raise ContextLeaseLost
                await append_snapshot(
                    db,
                    run_id,
                    self.worker_id,
                    f"tool:{call_id}",
                    "tool",
                    {
                        "name": name,
                        "toolCallId": call_id,
                        "status": "RUNNING",
                        "input": preview(arguments or {}),
                        "output": None,
                        "error": None,
                    },
                )
                if name == "skill.read":
                    args = arguments or {}
                    skill = next(
                        (
                            item
                            for item in skill_config or []
                            if item.get("name") == args.get("name")
                        ),
                        {},
                    )
                    self.skill_metadata[call_id] = {
                        "name": args.get("name", ""),
                        "toolCallId": call_id,
                        "resource": args.get("resource"),
                        "revision": skill.get("revision"),
                        "contentHash": skill.get("content_hash"),
                    }
                    await append_snapshot(
                        db,
                        run_id,
                        self.worker_id,
                        f"skill:{call_id}",
                        "skill",
                        {**self.skill_metadata[call_id], "status": "LOADING"},
                    )
            await db.commit()
            return row

    async def finish(
        self, run_id: str, call_id: str, status: str, content: str | None, error_code: str | None
    ) -> None:
        async with self.session_factory() as db:
            recorder = ExecutionRecorder(db)
            if not await recorder.owns_run(run_id, self.worker_id):
                raise ContextLeaseLost
            row = await db.scalar(
                select(ToolExecution)
                .where(ToolExecution.run_id == run_id, ToolExecution.tool_call_id == call_id)
                .with_for_update()
            )
            if row is None:
                raise ValueError("ToolExecution 不存在")
            if row.status != "STARTED":
                return
            row.status = status
            row.result_content = content
            row.error_code = error_code
            row.completed_at = datetime.now(UTC)
            if (
                await recorder.append(
                    run_id,
                    "tool.completed" if status == "COMPLETED" else "tool.failed",
                    {"name": row.tool_name, "tool_call_id": call_id, "code": error_code},
                    worker_id=self.worker_id,
                    attempt=row.attempt,
                    ref_type="tool_execution",
                    ref_id=row.id,
                )
                is None
            ):
                raise ContextLeaseLost
            previous = await latest_snapshot(db, run_id, f"tool:{call_id}")
            activity = dict(
                previous.content
                if previous
                else {"name": row.tool_name, "toolCallId": call_id, "input": None}
            )
            activity.update(status=status, output=preview(content), error=error_code)
            await append_snapshot(db, run_id, self.worker_id, f"tool:{call_id}", "tool", activity)
            if row.tool_name == "skill.read":
                skill = await latest_snapshot(db, run_id, f"skill:{call_id}")
                if skill:
                    await append_snapshot(
                        db,
                        run_id,
                        self.worker_id,
                        f"skill:{call_id}",
                        "skill",
                        {
                            **skill.content,
                            "status": "LOADED" if status == "COMPLETED" else "FAILED",
                        },
                    )
            await db.commit()
