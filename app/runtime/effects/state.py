"""外部副作用的有限状态机；未知结果绝不重新发送。"""

from enum import StrEnum


class EffectStatus(StrEnum):
    PREPARED = "PREPARED"
    DISPATCHED = "DISPATCHED"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    UNCERTAIN = "UNCERTAIN"
    RECONCILING = "RECONCILING"
    MANUAL_REQUIRED = "MANUAL_REQUIRED"


class EffectAction(StrEnum):
    DISPATCH = "DISPATCH"
    RECONCILE = "RECONCILE"
    WAIT = "WAIT"
    REPLAY = "REPLAY"
    STOP = "STOP"


_RECOVERY_ACTIONS = {
    EffectStatus.PREPARED: EffectAction.DISPATCH,
    EffectStatus.DISPATCHED: EffectAction.RECONCILE,
    EffectStatus.UNCERTAIN: EffectAction.RECONCILE,
    EffectStatus.RECONCILING: EffectAction.WAIT,
    EffectStatus.SUCCEEDED: EffectAction.REPLAY,
    EffectStatus.FAILED: EffectAction.STOP,
    EffectStatus.MANUAL_REQUIRED: EffectAction.STOP,
}

_TRANSITIONS = {
    (EffectStatus.PREPARED, "dispatch"): EffectStatus.DISPATCHED,
    (EffectStatus.DISPATCHED, "observed_success"): EffectStatus.SUCCEEDED,
    (EffectStatus.DISPATCHED, "observed_not_applied"): EffectStatus.FAILED,
    (EffectStatus.DISPATCHED, "unknown"): EffectStatus.UNCERTAIN,
    (EffectStatus.UNCERTAIN, "begin_reconcile"): EffectStatus.RECONCILING,
    (EffectStatus.RECONCILING, "observed_success"): EffectStatus.SUCCEEDED,
    (EffectStatus.RECONCILING, "observed_not_applied"): EffectStatus.FAILED,
    (EffectStatus.RECONCILING, "unknown"): EffectStatus.MANUAL_REQUIRED,
}


def recovery_action(status: EffectStatus) -> EffectAction:
    return _RECOVERY_ACTIONS[status]


def transition(status: EffectStatus, event: str) -> EffectStatus:
    try:
        return _TRANSITIONS[(status, event)]
    except KeyError as exc:
        raise ValueError(f"Effect 状态不允许转换：{status} + {event}") from exc
