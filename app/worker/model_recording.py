"""模型调用与 PostgreSQL 事实的边界；提交后才允许继续执行。"""

import asyncio
import time

from langchain_core.messages import BaseMessage
from sqlalchemy import select

from app.context.errors import ContextBudgetExceeded, ContextLeaseLost
from app.execution.message_content import model_content
from app.execution.model_serialization import serialize_model_input, serialize_model_output
from app.persistence.database import ModelExecution
from app.persistence.repositories.activity import (
    append_snapshot,
    bounded,
    latest_snapshot,
)
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
        self.partials = {}
        self.last_write = {}
        self.step_locks = {}
        self.execution_steps = {}

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

    async def _start(self, step_id: str, phase: str, messages: list[BaseMessage]) -> str:
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
            if phase == "AGENT":
                self.partials[step_id] = {
                    "stepId": step_id,
                    "status": "RUNNING",
                    "text": "",
                    "reasoning": "",
                }
                await append_snapshot(
                    db, self.run_id, self.worker_id, step_id, "model", self.partials[step_id]
                )
            await db.commit()
            return row.id

    async def _complete(self, execution_id: str, message: BaseMessage) -> None:
        async with self.session_factory() as db:
            if not await ExecutionRecorder(db).complete_model(
                execution_id, self.worker_id, serialize_model_output(message)
            ):
                raise ContextLeaseLost
            row = await db.get(ModelExecution, execution_id)
            if row.phase == "AGENT":
                text, reasoning = model_content(message)
                partial = self.partials.get(row.step_id, {})
                content = {
                    "stepId": row.step_id,
                    "status": "COMPLETED",
                    "text": bounded(text or partial.get("text", "")),
                    "reasoning": bounded(reasoning or partial.get("reasoning", "")),
                }
                await append_snapshot(
                    db, self.run_id, self.worker_id, row.step_id, "model", content
                )
                self.partials.pop(row.step_id, None)
            await db.commit()

    async def _stream(self, step_id: str, message: BaseMessage) -> None:
        content = self.partials.get(step_id)
        if content is None:
            return
        text, reasoning = model_content(message)
        updated_text = bounded(content["text"] + text)
        updated_reasoning = bounded(content["reasoning"] + reasoning)
        if (updated_text, updated_reasoning) == (content["text"], content["reasoning"]):
            return
        content["text"] = updated_text
        content["reasoning"] = updated_reasoning
        now = time.monotonic()
        if now - self.last_write.get(step_id, 0) < 0.2:
            return
        async with self.session_factory() as db:
            await append_snapshot(db, self.run_id, self.worker_id, step_id, "model", dict(content))
            await db.commit()
        self.last_write[step_id] = now

    async def _fail(self, execution_id: str, code: str = "MODEL_ERROR") -> None:
        async with self.session_factory() as db:
            if not await ExecutionRecorder(db).fail_model(execution_id, self.worker_id, code):
                raise ContextLeaseLost
            row = await db.get(ModelExecution, execution_id)
            if row.phase == "AGENT":
                partial = self.partials.pop(row.step_id, None)
                previous = await latest_snapshot(db, self.run_id, row.step_id)
                content = dict(
                    partial
                    or (
                        previous.content
                        if previous
                        else {"stepId": row.step_id, "text": "", "reasoning": ""}
                    )
                )
                content["status"] = "CANCELLED" if code == "MODEL_CANCELLED" else "FAILED"
                await append_snapshot(
                    db, self.run_id, self.worker_id, row.step_id, "model", content
                )
            await db.commit()

    def _lock(self, step_id):
        return self.step_locks.setdefault(step_id, asyncio.Lock())

    async def start(self, step_id: str, phase: str, messages: list[BaseMessage]) -> str:
        async with self._lock(step_id):
            execution_id = await self._start(step_id, phase, messages)
            self.execution_steps[execution_id] = step_id
            return execution_id

    async def _step_for_execution(self, execution_id):
        if execution_id not in self.execution_steps:
            async with self.session_factory() as db:
                row = await db.get(ModelExecution, execution_id)
                if row is None:
                    raise ContextLeaseLost
                self.execution_steps[execution_id] = row.step_id
        return self.execution_steps[execution_id]

    async def complete(self, execution_id: str, message: BaseMessage) -> None:
        async with self._lock(await self._step_for_execution(execution_id)):
            await self._complete(execution_id, message)

    async def stream(self, step_id: str, message: BaseMessage) -> None:
        async with self._lock(step_id):
            await self._stream(step_id, message)

    async def fail(self, execution_id: str, code: str = "MODEL_ERROR") -> None:
        async with self._lock(await self._step_for_execution(execution_id)):
            await self._fail(execution_id, code)
