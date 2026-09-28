from types import SimpleNamespace

from app.runtime.context import build_context
from app.runtime.middleware import ToolErrorMiddleware


async def test_tool_timeout_becomes_error_message():
    request = SimpleNamespace(tool_call={"name": "slow", "id": "call-timeout"})

    async def timeout(_request):
        raise TimeoutError("secret internal detail")

    result = await ToolErrorMiddleware().awrap_tool_call(request, timeout)
    assert result.status == "error"
    assert result.tool_call_id == "call-timeout"
    assert "secret internal detail" not in result.content


def test_context_builder_keeps_recent_session_messages_only():
    history = [
        SimpleNamespace(role="user", content="旧消息"),
        SimpleNamespace(role="assistant", content="旧回答"),
        SimpleNamespace(role="user", content="当前问题"),
    ]
    messages = build_context(history, max_messages=2)
    assert [message.content for message in messages] == ["旧回答", "当前问题"]
