"""从持久 Tool 事实构建 Working Context 引用。"""

import hashlib

from sqlalchemy import select

from app.context.working import ToolFactRef
from app.persistence.database import ToolExecution


async def load_tool_fact_refs(session_factory, run_id: str) -> dict[str, ToolFactRef]:
    async with session_factory() as db:
        rows = (
            await db.scalars(
                select(ToolExecution).where(
                    ToolExecution.run_id == run_id, ToolExecution.status == "COMPLETED"
                )
            )
        ).all()
    return {
        row.tool_call_id: ToolFactRef(
            row.id, hashlib.sha256(row.result_content.encode()).hexdigest()
        )
        for row in rows
        if row.result_content is not None
    }
