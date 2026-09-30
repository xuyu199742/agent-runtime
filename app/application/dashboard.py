from app.messaging.run_queue import RunQueue
from app.messaging.worker_registry import WorkerRegistry
from app.persistence.repositories.dashboard import DashboardRepository


class DashboardService:
    def __init__(self, repository: DashboardRepository, registry: WorkerRegistry, queue: RunQueue):
        self.repository = repository
        self.registry = registry
        self.queue = queue

    async def overview(self):
        data = await self.repository.summary()
        workers = await self.registry.list()
        return {
            **data,
            "worker_capacity": sum(worker["capacity"] for worker in workers),
            "worker_running": sum(worker["running"] for worker in workers),
            "queue_depth": await self.queue.depth(),
        }
