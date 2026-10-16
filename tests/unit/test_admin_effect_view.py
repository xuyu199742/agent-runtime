from datetime import UTC, datetime
from types import SimpleNamespace

from app.transport.http.v1.admin.runs import tool_executions


async def test_admin_tool_executions_shows_masked_effect_state():
    effect = SimpleNamespace(
        id="effect-1",
        status="MANUAL_REQUIRED",
        business_key="ticket:create:private-warning-100",
        external_ref=None,
        error_code="EFFECT_MANUAL_REQUIRED",
    )
    call = SimpleNamespace(
        id="call-1",
        tool_call_id="model-call-1",
        tool_name="ticket.create",
        effect_type="EXTERNAL_WRITE",
        idempotency_key="run-1:model-call-1",
        args_hash="a" * 64,
        status="FAILED",
        attempt=1,
        error_code="EFFECT_MANUAL_REQUIRED",
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC),
        effect_id="effect-1",
    )

    class Runs:
        async def tool_executions(self, _run_id):
            return [call], {effect.id: effect}

    result = await tool_executions("run-1", None, Runs())
    assert result[0]["effect"]["status"] == "MANUAL_REQUIRED"
    assert result[0]["effect"]["error_code"] == "EFFECT_MANUAL_REQUIRED"
    assert "private-warning-100" not in str(result)
