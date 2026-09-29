from types import SimpleNamespace

from app.runtime.context import build_context


def test_context_limits_one_oversized_message_and_keeps_latest():
    history = [
        SimpleNamespace(role="user", content="旧消息"),
        SimpleNamespace(role="user", content="中" * 100_000),
    ]
    context = build_context(history, max_messages=30, max_tokens=100)
    assert len(context) == 1
    assert len(context[0].content) < 100_000
    assert "旧消息" not in context[0].content


def test_context_reuses_recent_messages_within_both_limits():
    history = [SimpleNamespace(role="user", content=str(i)) for i in range(5)]
    context = build_context(history, max_messages=2, max_tokens=100)
    assert [item.content for item in context] == ["3", "4"]
