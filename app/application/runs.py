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

    async def execution_spec(self, run_id: str):
        run = await self.repository.get(run_id)
        if run is None:
            raise NotFound("Run 不存在")
        if run.execution_spec_id is None:
            return None
        spec = await self.repository.execution_spec(run.execution_spec_id)
        if spec is None:
            raise NotFound("ExecutionSpec 不存在")
        snapshot = {**spec.snapshot, "model": {**spec.snapshot["model"]}}
        snapshot["model"].pop("api_key_encrypted", None)
        return {
            "id": spec.id,
            "agent_id": spec.agent_id,
            "agent_revision": spec.agent_revision,
            "schema_version": spec.schema_version,
            "runtime_version": spec.runtime_version,
            "snapshot": snapshot,
            "created_at": spec.created_at,
        }

    async def tool_executions(self, run_id: str):
        if await self.repository.get(run_id) is None:
            raise NotFound("Run 不存在")
        return await self.repository.tool_executions(run_id)

    async def retry(self, run_id: str):
        retry = await self.repository.retry(run_id)
        if retry is None:
            raise NotFound("Run 不存在")
        return retry

    async def cancel_pending(self, run_id: str) -> bool:
        return await self.repository.cancel_pending(run_id)

    async def cancel_waiting(self, run_id: str) -> bool:
        return await self.repository.cancel_waiting(run_id)

    async def status(self, run_id: str) -> str | None:
        return await self.repository.status(run_id)

    async def release_read(self) -> None:
        await self.repository.release_read()
