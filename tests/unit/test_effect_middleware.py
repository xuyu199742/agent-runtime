from contextlib import asynccontextmanager
from types import SimpleNamespace

import pytest

from app.runtime.approval import ApprovalMiddleware
from app.runtime.errors import WriteNotAllowed
from app.runtime.middleware import EffectSafetyMiddleware


async def test_external_write_is_denied_without_explicit_policy_grant():
    request = SimpleNamespace(
        tool_call={"name": "ticket.create", "id": "call-1", "args": {"ticket_key": "T-1"}}
    )

    async def handler(_request):
        raise AssertionError("未授权写入不应调用 Tool")

    middleware = EffectSafetyMiddleware(
        store=object(),
        run_id="run-1",
        worker_id="worker-a",
        policies={"ticket.create": {"effect_type": "EXTERNAL_WRITE"}},
        providers={"ticket.create": object()},
    )
    with pytest.raises(WriteNotAllowed):
        await middleware.awrap_tool_call(request, handler)


async def test_rejected_approval_does_not_enter_effect_middleware(monkeypatch):
    request = SimpleNamespace(tool_call={"name": "ticket.create", "id": "call-1", "args": {}})

    @asynccontextmanager
    async def fake_session_factory():
        yield object()

    async def fake_ensure(_self, *_args, **_kwargs):
        return SimpleNamespace(
            id="approval-1",
            title="创建工单",
            description="",
            risk="HIGH",
            tool_name="ticket.create",
        )

    async def effect_handler(_request):
        raise AssertionError("拒绝审批后不应进入 Effect Safety")

    monkeypatch.setattr("app.runtime.approval.ApprovalRepository.ensure", fake_ensure)
    monkeypatch.setattr("app.runtime.approval.interrupt", lambda _payload: False)
    middleware = ApprovalMiddleware(
        fake_session_factory,
        "run-1",
        {"ticket.create": {"policy": {"requires_approval": True}}},
        "worker-a",
    )
    result = await middleware.awrap_tool_call(request, effect_handler)
    assert result.status == "error"
