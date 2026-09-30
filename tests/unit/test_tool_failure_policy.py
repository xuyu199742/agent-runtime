from types import SimpleNamespace

import pytest

from app.runtime.middleware import ToolErrorMiddleware


async def test_tool_failure_policy_controls_run_failure():
    request = SimpleNamespace(tool_call={"name": "echo", "id": "call", "args": {"text": "x"}})

    async def fail(_request):
        raise TimeoutError("tool timed out")

    returned = await ToolErrorMiddleware().awrap_tool_call(request, fail)
    assert returned.status == "error"
    assert "timed out" not in returned.content

    middleware = ToolErrorMiddleware(policies={"echo": {"failure_policy": "FAIL_RUN"}})
    with pytest.raises(TimeoutError):
        await middleware.awrap_tool_call(request, fail)
