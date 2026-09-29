import asyncio

import structlog
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver

from app.persistence.database import session_factory
from app.persistence.repositories.runs import expired_checkpoint_run_ids, mark_checkpoint_pruned

log = structlog.get_logger()


async def cleanup_checkpoints(saver: AsyncPostgresSaver, retention_hours: int) -> int:
    async with session_factory() as db:
        run_ids = await expired_checkpoint_run_ids(db, retention_hours)
    cleaned = 0
    for run_id in run_ids:
        await saver.adelete_thread(run_id)
        async with session_factory() as db:
            await mark_checkpoint_pruned(db, run_id)
        cleaned += 1
    return cleaned


async def sweep_checkpoints(saver: AsyncPostgresSaver, retention_hours: int) -> None:
    while True:
        try:
            count = await cleanup_checkpoints(saver, retention_hours)
            if count:
                log.info("已清理过期 Checkpoint", count=count)
        except Exception:
            log.exception("Checkpoint 清理失败，下次重试")
        await asyncio.sleep(3600)
