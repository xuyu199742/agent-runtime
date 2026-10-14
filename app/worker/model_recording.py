"""模型调用与 PostgreSQL 事实的边界；提交后才允许继续执行。"""

from langchain_core.messages import BaseMessage

from app.context.errors import ContextLeaseLost
from app.execution.model_serialization import serialize_model_input, serialize_model_output
from app.persistence.repositories.traces import ExecutionRecorder


class ModelCallJournal:
    def __init__(
        self, session_factory, run_id: str, worker_id: str, provider: str, model_name: str
    ) -> None:
        self.session_factory = session_factory
        self.run_id = run_id
        self.worker_id = worker_id
        self.provider = provider
        self.model_name = model_name

    async def start(self, step_id: str, phase: str, messages: list[BaseMessage]) -> str:
        async with self.session_factory() as db:
            row = await ExecutionRecorder(db).start_model(
                self.run_id,
                self.worker_id,
                step_id=step_id,
                phase=phase,
                provider=self.provider,
                model_name=self.model_name,
                input_messages=serialize_model_input(messages),
            )
            if row is None:
                raise ContextLeaseLost
            await db.commit()
            return row.id

    async def complete(self, execution_id: str, message: BaseMessage) -> None:
        async with self.session_factory() as db:
            if not await ExecutionRecorder(db).complete_model(
                execution_id, self.worker_id, serialize_model_output(message)
            ):
                raise ContextLeaseLost
            await db.commit()

    async def fail(self, execution_id: str, code: str = "MODEL_ERROR") -> None:
        async with self.session_factory() as db:
            if not await ExecutionRecorder(db).fail_model(execution_id, self.worker_id, code):
                raise ContextLeaseLost
            await db.commit()
