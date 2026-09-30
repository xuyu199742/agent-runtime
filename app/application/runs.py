from app.domain.errors import NotFound
from app.persistence.repositories.runs import RunRepository


class RunService:
    def __init__(self, repository: RunRepository) -> None:
        self.repository = repository

    async def visible(self, run_id: str, user_id: str):
        run = await self.repository.visible(run_id, user_id)
        if run is None:
            raise NotFound("Run 不存在")
        return run

    async def detail(self, run_id: str, user_id: str):
        run = await self.visible(run_id, user_id)
        answer = (
            await self.repository.answer(run.answer_message_id) if run.answer_message_id else None
        )
        return run, answer.content if answer else None

    async def list_runs(
        self,
        page: int,
        page_size: int,
        user_id=None,
        status=None,
        agent_id=None,
        worker_id=None,
        error_code=None,
    ):
        return await self.repository.list_runs(
            page, page_size, user_id, status, agent_id, worker_id, error_code
        )

    async def admin_detail(self, run_id: str):
        run = await self.repository.get(run_id)
        if run is None:
            raise NotFound("Run 不存在")
        answer = (
            await self.repository.answer(run.answer_message_id) if run.answer_message_id else None
        )
        context = await self.repository.admin_context(run_id)
        return run, answer.content if answer else None, context

    async def cancel_pending(self, run_id: str) -> bool:
        return await self.repository.cancel_pending(run_id)

    async def status(self, run_id: str) -> str | None:
        return await self.repository.status(run_id)

    async def release_read(self) -> None:
        await self.repository.release_read()
