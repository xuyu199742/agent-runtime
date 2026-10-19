"""跨 Run 外部副作用身份和发送权的持久化。"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.context.errors import ContextLeaseLost
from app.persistence.database import EffectRecord, Run, ToolExecution, new_id
from app.persistence.repositories.traces import ExecutionRecorder
from app.runtime.effects.state import EffectStatus, transition
from app.runtime.errors import EffectIdempotencyConflictError, EffectResultUnavailable


class EffectStore:
    def __init__(self, session_factory):
        self.session_factory = session_factory

    async def get(self, effect_id: str) -> EffectRecord:
        async with self.session_factory() as db:
            row = await db.get(EffectRecord, effect_id)
            if row is None:
                raise ValueError("Effect 不存在")
            return row

    async def prepare(
        self,
        run_id: str,
        worker_id: str,
        provider_namespace: str,
        operation_name: str,
        business_key: str,
        contract_version: int,
        request_hash: str,
        call_id: str | None = None,
    ) -> EffectRecord:
        async with self.session_factory() as db:
            recorder = ExecutionRecorder(db)
            if not await recorder.owns_run(run_id, worker_id):
                raise ContextLeaseLost
            created_id = await db.scalar(
                insert(EffectRecord)
                .values(
                    id=new_id(),
                    provider_namespace=provider_namespace,
                    operation_name=operation_name,
                    business_key=business_key,
                    contract_version=contract_version,
                    request_hash=request_hash,
                    status=EffectStatus.PREPARED,
                    origin_run_id=run_id,
                )
                .on_conflict_do_nothing(constraint="uq_effect_identity")
                .returning(EffectRecord.id)
            )
            row = await db.scalar(
                select(EffectRecord)
                .where(
                    EffectRecord.provider_namespace == provider_namespace,
                    EffectRecord.operation_name == operation_name,
                    EffectRecord.business_key == business_key,
                )
                .with_for_update()
            )
            if row is None:
                raise RuntimeError("Effect 写入后未找到记录")
            if row.contract_version != contract_version or row.request_hash != request_hash:
                raise EffectIdempotencyConflictError("相同业务键对应不同写入请求")
            if call_id is not None:
                created_call = await db.scalar(
                    insert(ToolExecution)
                    .values(
                        id=new_id(),
                        run_id=run_id,
                        tool_call_id=call_id,
                        tool_name=operation_name,
                        effect_type="EXTERNAL_WRITE",
                        idempotency_key=f"{run_id}:{call_id}",
                        args_hash=request_hash,
                        status="STARTED",
                        attempt=1,
                        effect_id=row.id,
                    )
                    .on_conflict_do_nothing(index_elements=["run_id", "tool_call_id"])
                    .returning(ToolExecution.id)
                )
                call = await db.scalar(
                    select(ToolExecution)
                    .where(ToolExecution.run_id == run_id, ToolExecution.tool_call_id == call_id)
                    .with_for_update()
                )
                if (
                    call is None
                    or call.effect_id != row.id
                    or call.tool_name != operation_name
                    or call.args_hash != request_hash
                ):
                    raise EffectIdempotencyConflictError("Tool Call ID 与既有 Effect 不一致")
                if created_call is not None and (
                    await recorder.append(
                        run_id,
                        "tool.started",
                        {"name": operation_name, "tool_call_id": call_id},
                        worker_id=worker_id,
                        ref_type="tool_execution",
                        ref_id=call.id,
                    )
                    is None
                ):
                    raise ContextLeaseLost
                if row.status == EffectStatus.SUCCEEDED and call.status != "COMPLETED":
                    if row.result_content is None:
                        raise EffectResultUnavailable("已成功的 Effect 缺少可重放结果")
                    call.status = "COMPLETED"
                    call.result_content = row.result_content
                    call.completed_at = datetime.now(UTC)
                    if (
                        await recorder.append(
                            run_id,
                            "tool.completed",
                            {"name": operation_name, "tool_call_id": call_id},
                            worker_id=worker_id,
                            ref_type="tool_execution",
                            ref_id=call.id,
                        )
                        is None
                    ):
                        raise ContextLeaseLost
                    if (
                        await recorder.append(
                            run_id,
                            "effect.reused",
                            {"name": operation_name, "tool_call_id": call_id},
                            worker_id=worker_id,
                            ref_type="effect",
                            ref_id=row.id,
                        )
                        is None
                    ):
                        raise ContextLeaseLost
                if (
                    row.status in {EffectStatus.FAILED, EffectStatus.MANUAL_REQUIRED}
                    and call.status != "FAILED"
                ):
                    call.status = "FAILED"
                    call.error_code = (
                        "EFFECT_NOT_APPLIED"
                        if row.status == EffectStatus.FAILED
                        else "EFFECT_MANUAL_REQUIRED"
                    )
                    call.completed_at = datetime.now(UTC)
                    if (
                        await recorder.append(
                            run_id,
                            "tool.failed",
                            {
                                "name": operation_name,
                                "tool_call_id": call_id,
                                "code": call.error_code,
                            },
                            worker_id=worker_id,
                            ref_type="tool_execution",
                            ref_id=call.id,
                        )
                        is None
                    ):
                        raise ContextLeaseLost
            if created_id is not None and (
                await recorder.append(
                    run_id,
                    "effect.prepared",
                    {"name": operation_name},
                    worker_id=worker_id,
                    ref_type="effect",
                    ref_id=row.id,
                )
                is None
            ):
                raise ContextLeaseLost
            await db.commit()
            return row

    async def claim_dispatch(self, effect_id: str, run_id: str, worker_id: str) -> bool:
        async with self.session_factory() as db:
            recorder = ExecutionRecorder(db)
            if not await recorder.owns_run(run_id, worker_id):
                raise ContextLeaseLost
            row = await db.scalar(
                select(EffectRecord).where(EffectRecord.id == effect_id).with_for_update()
            )
            if row is None:
                raise ValueError("Effect 不存在")
            if row.status != EffectStatus.PREPARED:
                return False
            row.status = transition(EffectStatus(row.status), "dispatch")
            row.dispatch_run_id = run_id
            row.dispatch_worker_id = worker_id
            row.dispatched_at = datetime.now(UTC)
            if (
                await recorder.append(
                    run_id,
                    "effect.dispatched",
                    {"name": row.operation_name},
                    worker_id=worker_id,
                    ref_type="effect",
                    ref_id=row.id,
                )
                is None
            ):
                raise ContextLeaseLost
            await db.commit()
            return True

    async def begin_reconcile(self, effect_id: str, run_id: str, worker_id: str) -> bool:
        """只允许一个有效 Run 核对；失租后可接管。"""
        async with self.session_factory() as db:
            recorder = ExecutionRecorder(db)
            if not await recorder.owns_run(run_id, worker_id):
                raise ContextLeaseLost
            row = await db.scalar(
                select(EffectRecord).where(EffectRecord.id == effect_id).with_for_update()
            )
            if row is None:
                raise ValueError("Effect 不存在")
            if row.status == EffectStatus.RECONCILING:
                owner = await db.get(Run, row.reconcile_run_id) if row.reconcile_run_id else None
                if (
                    owner is not None
                    and owner.status == "RUNNING"
                    and owner.lease_until is not None
                    and owner.lease_until > datetime.now(UTC)
                    and (owner.id != run_id or row.reconcile_worker_id == worker_id)
                ):
                    return False
            elif row.status == EffectStatus.UNCERTAIN:
                row.status = transition(EffectStatus(row.status), "begin_reconcile")
            else:
                return False
            row.reconcile_run_id = run_id
            row.reconcile_worker_id = worker_id
            if (
                await recorder.append(
                    run_id,
                    "effect.reconciling",
                    {"name": row.operation_name},
                    worker_id=worker_id,
                    ref_type="effect",
                    ref_id=row.id,
                )
                is None
            ):
                raise ContextLeaseLost
            await db.commit()
            return True

    async def advance(
        self,
        effect_id: str,
        run_id: str,
        worker_id: str,
        event: str,
        *,
        result_content: str | None = None,
        external_ref: str | None = None,
        call_id: str | None = None,
    ) -> EffectRecord:
        """效果事实及对应 Timeline 在同一事务更新。"""
        async with self.session_factory() as db:
            recorder = ExecutionRecorder(db)
            if not await recorder.owns_run(run_id, worker_id):
                raise ContextLeaseLost
            row = await db.scalar(
                select(EffectRecord).where(EffectRecord.id == effect_id).with_for_update()
            )
            if row is None:
                raise ValueError("Effect 不存在")
            if row.status == EffectStatus.DISPATCHED and row.dispatch_run_id != run_id:
                owner = await db.get(Run, row.dispatch_run_id) if row.dispatch_run_id else None
                if (
                    owner is not None
                    and owner.status == "RUNNING"
                    and owner.lease_until is not None
                    and owner.lease_until > datetime.now(UTC)
                ):
                    raise ValueError("原发送者仍持有有效租约")
                if event != "unknown":
                    raise ValueError("其他 Run 只能先将已发送 Effect 标为未知")
            if row.status == EffectStatus.RECONCILING and row.reconcile_run_id != run_id:
                raise ValueError("当前 Run 未取得核对权")
            if event == "observed_success" and result_content is None:
                raise EffectResultUnavailable("成功 Effect 缺少可重放结果")
            row.status = transition(EffectStatus(row.status), event)
            if row.status == EffectStatus.SUCCEEDED:
                row.result_content = result_content
                row.external_ref = external_ref
                row.resolved_at = datetime.now(UTC)
            elif row.status == EffectStatus.FAILED:
                row.error_code = "EFFECT_NOT_APPLIED"
                row.resolved_at = datetime.now(UTC)
            elif row.status == EffectStatus.MANUAL_REQUIRED:
                row.error_code = "EFFECT_MANUAL_REQUIRED"
            if call_id is not None and row.status in {
                EffectStatus.SUCCEEDED,
                EffectStatus.FAILED,
                EffectStatus.MANUAL_REQUIRED,
            }:
                call = await db.scalar(
                    select(ToolExecution)
                    .where(ToolExecution.run_id == run_id, ToolExecution.tool_call_id == call_id)
                    .with_for_update()
                )
                if call is None or call.effect_id != row.id:
                    raise ValueError("ToolExecution 未关联当前 Effect")
                call.status = "COMPLETED" if row.status == EffectStatus.SUCCEEDED else "FAILED"
                call.result_content = (
                    result_content if row.status == EffectStatus.SUCCEEDED else None
                )
                call.error_code = None if row.status == EffectStatus.SUCCEEDED else row.error_code
                call.completed_at = datetime.now(UTC)
                if (
                    await recorder.append(
                        run_id,
                        "tool.completed" if call.status == "COMPLETED" else "tool.failed",
                        {
                            "name": row.operation_name,
                            "tool_call_id": call_id,
                            "code": call.error_code,
                        },
                        worker_id=worker_id,
                        ref_type="tool_execution",
                        ref_id=call.id,
                    )
                    is None
                ):
                    raise ContextLeaseLost
            event_type = {
                EffectStatus.SUCCEEDED: "effect.succeeded",
                EffectStatus.FAILED: "effect.failed",
                EffectStatus.UNCERTAIN: "effect.uncertain",
                EffectStatus.MANUAL_REQUIRED: "effect.manual_required",
            }[EffectStatus(row.status)]
            if (
                await recorder.append(
                    run_id,
                    event_type,
                    {"name": row.operation_name},
                    worker_id=worker_id,
                    ref_type="effect",
                    ref_id=row.id,
                )
                is None
            ):
                raise ContextLeaseLost
            await db.commit()
            return row
