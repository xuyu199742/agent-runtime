"""模型调用与 PostgreSQL 事实的边界；提交后才允许继续执行。"""

from langchain_core.messages import BaseMessage
from sqlalchemy import select

from app.context.errors import ContextBudgetExceeded, ContextLeaseLost
from app.execution.model_serialization import serialize_model_input, serialize_model_output
from app.persistence.database import ModelExecution
from app.persistence.repositories.traces import ExecutionRecorder


class ModelCallJournal:
    def __init__(
        self,
        session_factory,
        run_id: str,
        worker_id: str,
        provider: str,
        model_name: str,
        budget=None,
    ) -> None:
        self.session_factory = session_factory
        self.run_id = run_id
        self.worker_id = worker_id
        self.provider = provider
        self.model_name = model_name
        self.budget = budget

    async def ensure_working_batch(self, step_id: str, graph_step: int, limit: int) -> None:
        async with self.session_factory() as db:
            recorder = ExecutionRecorder(db)
            if not await recorder.owns_run(self.run_id, self.worker_id):
                raise ContextLeaseLost
            step_ids = (
                await db.scalars(
                    select(ModelExecution.step_id).where(
                        ModelExecution.run_id == self.run_id,
                        ModelExecution.phase == "CONTEXT_SUMMARY",
                    )
                )
            ).all()
            prefix = f"{self.run_id}:working:"
            working_steps = {item for item in step_ids if item.startswith(prefix)}
            graph_prefix = f"{prefix}{graph_step}:"
            used_in_step = sum(item.startswith(graph_prefix) for item in working_steps)
            if step_id in working_steps:
                return
            if used_in_step >= limit or (
                self.budget is not None
                and len(working_steps) >= self.budget.max_model_calls * limit
            ):
                raise ContextBudgetExceeded("Working Context 压缩轮数不足")

    async def completed_summary(self, step_id: str, messages: list[BaseMessage]) -> str | None:
        async with self.session_factory() as db:
            result = await ExecutionRecorder(db).completed_summary(
                self.run_id,
                self.worker_id,
                step_id,
                serialize_model_input(messages),
            )
            return result

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
                budget=self.budget,
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
