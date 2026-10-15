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


async def test_completed_tool_without_result_fails_closed():
    request = SimpleNamespace(tool_call={"name": "echo", "id": "call", "args": {"text": "x"}})

    class Store:
        async def start(self, *_args):
            return SimpleNamespace(status="COMPLETED", result_content=None)

        async def finish(self, *_args):
            raise AssertionError("已完成调用不能改成失败")

    async def execute(_request):
        raise AssertionError("已完成调用不能再次执行")

    middleware = ToolErrorMiddleware(store=Store(), run_id="run")
    with pytest.raises(Exception) as error:
        await middleware.awrap_tool_call(request, execute)
    assert type(error.value).__name__ == "ToolResultUnavailable"
