from types import SimpleNamespace

from app.transport.agui import map_trace_event, terminal_events


def test_tool_trace_maps_to_standard_events_without_args_or_secrets():
    started = SimpleNamespace(
        event_type="tool.started",
        sequence=3,
        data={
            "tool_call_id": "call-1",
            "name": "lookup",
            "api_key": "secret",
            "args": {"token": "secret"},
        },
    )
    completed = SimpleNamespace(
        event_type="tool.completed",
        sequence=4,
        data={"tool_call_id": "call-1", "name": "lookup", "result": "private"},
    )
    first = map_trace_event(started)
    second = map_trace_event(completed)
    assert first[0]["type"] == "TOOL_CALL_START"
    assert first[0]["toolCallId"] == "call-1"
    assert second[0]["type"] == "TOOL_CALL_END"
    assert "secret" not in str(first)
    assert "private" not in str(second)


def test_terminal_events_use_answer_and_interrupt_outcome():
    complete = terminal_events("thread", "run", "COMPLETED", "message-1", "answer", None, [])
    assert [event["type"] for event in complete] == [
        "TEXT_MESSAGE_START",
        "TEXT_MESSAGE_CONTENT",
        "TEXT_MESSAGE_END",
        "RUN_FINISHED",
    ]
    assert complete[1]["delta"] == "answer"
    waiting = terminal_events(
        "thread",
        "run",
        "WAITING",
        None,
        None,
        None,
        [{"id": "approval-1", "tool_call_id": "call-1", "title": "Approve", "risk": "HIGH"}],
    )
    assert waiting[-1]["outcome"]["type"] == "interrupt"
    assert waiting[-1]["outcome"]["interrupts"][0]["id"] == "approval-1"


def test_activity_mapping_exposes_only_safe_fields():
    row = SimpleNamespace(
        event_type="approval.required",
        sequence=8,
        data={"approval_id": "approval-1", "tool_call_id": "call-1", "token": "secret"},
    )
    events = map_trace_event(row)
    assert events[0]["type"] == "ACTIVITY_SNAPSHOT"
    assert events[0]["messageId"] == "approval:approval-1"
    assert "secret" not in str(events)
    cancelled = terminal_events("thread", "run", "CANCELLED", None, None, None, [])
    assert cancelled[-1]["outcome"]["type"] == "cancelled"
    failed = terminal_events("thread", "run", "FAILED", None, None, "TOOL_FAILED", [])
    assert failed[-1]["type"] == "RUN_ERROR"
