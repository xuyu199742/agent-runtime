from app.runtime.errors import (
    EffectIdempotencyConflictError,
    EffectManualRequired,
    EffectResultUnavailable,
    EffectUncertain,
)
from app.worker.runner import classify_run_error


def test_effect_errors_keep_stable_run_codes():
    for error, code in (
        (EffectIdempotencyConflictError(), "EFFECT_IDEMPOTENCY_CONFLICT"),
        (EffectUncertain(), "EFFECT_UNCERTAIN"),
        (EffectManualRequired(), "EFFECT_MANUAL_REQUIRED"),
        (EffectResultUnavailable(), "EFFECT_RESULT_UNAVAILABLE"),
    ):
        assert classify_run_error(error) == code
