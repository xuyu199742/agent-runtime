import pytest

from app.runtime.effects.state import EffectAction, EffectStatus, recovery_action, transition


@pytest.mark.parametrize(
    ("status", "action"),
    [
        (EffectStatus.PREPARED, EffectAction.DISPATCH),
        (EffectStatus.DISPATCHED, EffectAction.RECONCILE),
        (EffectStatus.UNCERTAIN, EffectAction.RECONCILE),
        (EffectStatus.RECONCILING, EffectAction.WAIT),
        (EffectStatus.SUCCEEDED, EffectAction.REPLAY),
        (EffectStatus.FAILED, EffectAction.STOP),
        (EffectStatus.MANUAL_REQUIRED, EffectAction.STOP),
    ],
)
def test_recovery_action_never_redispatches_unknown_effect(status, action):
    assert recovery_action(status) is action


@pytest.mark.parametrize(
    ("old", "event", "new"),
    [
        (EffectStatus.PREPARED, "dispatch", EffectStatus.DISPATCHED),
        (EffectStatus.DISPATCHED, "observed_success", EffectStatus.SUCCEEDED),
        (EffectStatus.DISPATCHED, "observed_not_applied", EffectStatus.FAILED),
        (EffectStatus.DISPATCHED, "unknown", EffectStatus.UNCERTAIN),
        (EffectStatus.UNCERTAIN, "begin_reconcile", EffectStatus.RECONCILING),
        (EffectStatus.RECONCILING, "observed_success", EffectStatus.SUCCEEDED),
        (EffectStatus.RECONCILING, "observed_not_applied", EffectStatus.FAILED),
        (EffectStatus.RECONCILING, "unknown", EffectStatus.MANUAL_REQUIRED),
    ],
)
def test_explicit_effect_state_transitions(old, event, new):
    assert transition(old, event) is new


def test_successful_effect_cannot_be_dispatched_again():
    with pytest.raises(ValueError, match="不允许"):
        transition(EffectStatus.SUCCEEDED, "dispatch")
