"""受控外部写入：先持久化发送意图，未知结果只核对。"""

from app.runtime.effects.contract import EffectIdentity, EffectObservation, ObservationStatus
from app.runtime.effects.state import EffectStatus
from app.runtime.errors import (
    EffectManualRequired,
    EffectNotApplied,
    EffectResultUnavailable,
    EffectUncertain,
)


class EffectExecutor:
    def __init__(self, store, provider):
        self.store = store
        self.provider = provider

    async def execute(
        self, run_id: str, worker_id: str, args: dict, *, call_id: str | None = None
    ) -> str:
        identity: EffectIdentity = self.provider.identity(args)
        effect = await self.store.prepare(
            run_id,
            worker_id,
            identity.provider_namespace,
            identity.operation_name,
            identity.business_key,
            identity.contract_version,
            identity.request_hash,
            call_id,
        )
        if effect.status == EffectStatus.SUCCEEDED:
            if effect.result_content is None:
                raise EffectResultUnavailable("已成功的 Effect 缺少结果")
            return effect.result_content
        if effect.status == EffectStatus.PREPARED:
            if await self.store.claim_dispatch(effect.id, run_id, worker_id):
                return await self._invoke(effect.id, identity, run_id, worker_id, args, call_id)
            effect = await self.store.get(effect.id)
            if effect.status == EffectStatus.SUCCEEDED:
                return await self._replay(identity, run_id, worker_id, call_id)
        if effect.status == EffectStatus.DISPATCHED:
            try:
                await self.store.advance(effect.id, run_id, worker_id, "unknown")
            except ValueError as exc:
                latest = await self.store.get(effect.id)
                if latest.status == EffectStatus.SUCCEEDED:
                    return await self._replay(identity, run_id, worker_id, call_id)
                raise EffectUncertain("外部请求仍可能在执行") from exc
        elif effect.status == EffectStatus.MANUAL_REQUIRED:
            raise EffectManualRequired("Effect 需要人工核对")
        elif effect.status == EffectStatus.FAILED:
            raise EffectNotApplied("Effect 已确认未发生，不自动重发")
        if not await self.store.begin_reconcile(effect.id, run_id, worker_id):
            latest = await self.store.get(effect.id)
            if latest.status == EffectStatus.SUCCEEDED:
                return await self._replay(identity, run_id, worker_id, call_id)
            if latest.status == EffectStatus.MANUAL_REQUIRED:
                raise EffectManualRequired("Effect 需要人工核对")
            if latest.status == EffectStatus.FAILED:
                raise EffectNotApplied("Effect 已确认未发生，不自动重发")
            raise EffectUncertain("Effect 核对正在进行")
        return await self._reconcile(effect.id, identity, run_id, worker_id, call_id)

    async def _replay(
        self, identity: EffectIdentity, run_id: str, worker_id: str, call_id: str | None
    ) -> str:
        effect = await self.store.prepare(
            run_id,
            worker_id,
            identity.provider_namespace,
            identity.operation_name,
            identity.business_key,
            identity.contract_version,
            identity.request_hash,
            call_id,
        )
        if effect.result_content is None:
            raise EffectResultUnavailable("已成功的 Effect 缺少结果")
        return effect.result_content

    async def _invoke(
        self,
        effect_id: str,
        identity: EffectIdentity,
        run_id: str,
        worker_id: str,
        args: dict,
        call_id: str | None,
    ) -> str:
        try:
            observation: EffectObservation = await self.provider.invoke(args, identity.business_key)
        except Exception:  # noqa: BLE001 - 任意 Provider 异常都不足以证明外部写入未发生
            # 网络/超时/未知异常均不能证明远端未执行。
            await self.store.advance(effect_id, run_id, worker_id, "unknown")
            if not await self.store.begin_reconcile(effect_id, run_id, worker_id):
                raise EffectUncertain("Effect 核对正在进行") from None
            return await self._reconcile(effect_id, identity, run_id, worker_id, call_id)
        return await self._apply_observation(
            effect_id, identity, run_id, worker_id, observation, call_id, from_reconcile=False
        )

    async def _reconcile(
        self,
        effect_id: str,
        identity: EffectIdentity,
        run_id: str,
        worker_id: str,
        call_id: str | None,
    ) -> str:
        try:
            observation: EffectObservation = await self.provider.reconcile(identity)
        except Exception as exc:
            await self.store.advance(effect_id, run_id, worker_id, "unknown", call_id=call_id)
            raise EffectManualRequired("核对失败，需要人工确认") from exc
        return await self._apply_observation(
            effect_id, identity, run_id, worker_id, observation, call_id, from_reconcile=True
        )

    async def _apply_observation(
        self,
        effect_id: str,
        identity: EffectIdentity,
        run_id: str,
        worker_id: str,
        observation: EffectObservation,
        call_id: str | None,
        *,
        from_reconcile: bool,
    ) -> str:
        if observation.status == ObservationStatus.SUCCEEDED:
            await self.store.advance(
                effect_id,
                run_id,
                worker_id,
                "observed_success",
                result_content=observation.result_content,
                external_ref=observation.external_ref,
                call_id=call_id,
            )
            if observation.result_content is None:
                raise EffectResultUnavailable("成功 Effect 缺少结果")
            return observation.result_content
        if observation.status == ObservationStatus.NOT_APPLIED and observation.final:
            await self.store.advance(
                effect_id, run_id, worker_id, "observed_not_applied", call_id=call_id
            )
            raise EffectNotApplied("外部请求未发生，当前版本不自动重发")
        if not from_reconcile:
            await self.store.advance(effect_id, run_id, worker_id, "unknown")
            if not await self.store.begin_reconcile(effect_id, run_id, worker_id):
                raise EffectUncertain("Effect 核对正在进行")
            return await self._reconcile(effect_id, identity, run_id, worker_id, call_id)
        await self.store.advance(effect_id, run_id, worker_id, "unknown", call_id=call_id)
        raise EffectManualRequired("核对未能确认外部结果")
