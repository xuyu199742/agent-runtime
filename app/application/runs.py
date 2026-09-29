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

    async def cancel_pending(self, run_id: str) -> bool:
        return await self.repository.cancel_pending(run_id)

    async def status(self, run_id: str) -> str | None:
        return await self.repository.status(run_id)

    async def release_read(self) -> None:
        await self.repository.release_read()
