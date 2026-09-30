"""Tool 调用事实写入 PostgreSQL；唯一键为 Run 与模型生成的 Tool Call ID。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.persistence.database import ToolExecution


class ToolExecutionStore:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def start(
        self, run_id: str, call_id: str, name: str, effect_type: str, args_hash: str
    ) -> ToolExecution:
        async with self.session_factory() as db:
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
            await db.commit()
            return row

    async def finish(
        self, run_id: str, call_id: str, status: str, content: str | None, error_code: str | None
    ) -> None:
        async with self.session_factory() as db:
            row = await db.scalar(
                select(ToolExecution)
                .where(ToolExecution.run_id == run_id, ToolExecution.tool_call_id == call_id)
                .with_for_update()
            )
            row.status = status
            row.result_content = content
            row.error_code = error_code
            row.completed_at = datetime.now(UTC)
            await db.commit()
