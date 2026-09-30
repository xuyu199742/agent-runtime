from app.domain.errors import NotFound
from app.messaging.worker_registry import WorkerRegistry
from app.persistence.repositories.runs import RunRepository


class WorkerService:
    def __init__(self, registry: WorkerRegistry, runs: RunRepository):
        self.registry = registry
        self.runs = runs

    async def list(self):
        return await self.registry.list()

    async def detail(self, worker_id: str):
        worker = await self.registry.get(worker_id)
        if worker is None:
            raise NotFound("Worker 不在线")
        return {**worker, "current_runs": await self.runs.active_for_worker(worker_id)}
