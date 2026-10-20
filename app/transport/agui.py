"""把持久 Run 事实映射成 AG-UI 1.0 事件。"""

from ag_ui.core import (
    ActivitySnapshotEvent,
    Interrupt,
    RunErrorEvent,
    RunFinishedCancelledOutcome,
    RunFinishedEvent,
    RunFinishedInterruptOutcome,
    RunStartedEvent,
    TextMessageContentEvent,
    TextMessageEndEvent,
    TextMessageStartEvent,
    ToolCallEndEvent,
    ToolCallResultEvent,
    ToolCallStartEvent,
)


def wire(event) -> dict:
    return event.model_dump(by_alias=True, exclude_none=True, mode="json")


def run_started(thread_id: str, run_id: str) -> dict:
    return wire(RunStartedEvent(thread_id=thread_id, run_id=run_id, protocol_version="1.0"))


def activity(message_id: str, kind: str, content: dict) -> dict:
    return wire(ActivitySnapshotEvent(message_id=message_id, activity_type=kind, content=content))


def map_trace_event(row) -> list[dict]:
    kind = row.event_type
    data = row.data or {}
    call_id = data.get("tool_call_id")
    name = data.get("name")
    if kind == "tool.started" and call_id and name:
        return [
            wire(ToolCallStartEvent(tool_call_id=call_id, tool_call_name=name)),
            activity(f"tool:{call_id}", "tool", {"name": name, "status": "RUNNING"}),
        ]
    if kind in {"tool.completed", "tool.failed"} and call_id:
        status = "COMPLETED" if kind == "tool.completed" else "FAILED"
        return [
            wire(ToolCallEndEvent(tool_call_id=call_id)),
            wire(
                ToolCallResultEvent(
                    message_id=f"tool-result:{call_id}",
                    tool_call_id=call_id,
                    content="工具已完成" if status == "COMPLETED" else "工具执行失败",
                )
            ),
            activity(f"tool:{call_id}", "tool", {"name": name or "", "status": status}),
        ]
    if kind.startswith("approval.") and data.get("approval_id"):
        return [
            activity(
                f"approval:{data['approval_id']}",
                "approval",
                {
                    "approvalId": data["approval_id"],
                    "status": kind.split(".", 1)[1].upper(),
                    "toolCallId": call_id,
                },
            )
        ]
    if kind == "artifact.created" and data.get("artifact_id"):
        return [
            activity(
                f"artifact:{data['artifact_id']}",
                "artifact",
                {"artifactId": data["artifact_id"], "status": "CREATED"},
            )
        ]
    if kind.startswith("effect."):
        return [
            activity(
                f"effect:{row.sequence}",
                "effect",
                {
                    "status": kind.split(".", 1)[1].upper(),
                    "effectType": data.get("effect_type", "EXTERNAL_WRITE"),
                },
            )
        ]
    if kind in {"policy.denied", "budget.exceeded"}:
        return [
            activity(
                f"decision:{row.sequence}",
                "decision",
                {"status": kind, "code": data.get("code") or data.get("dimension")},
            )
        ]
    return []


def terminal_events(
    thread_id: str,
    run_id: str,
    status: str,
    answer_id: str | None,
    answer: str | None,
    error_code: str | None,
    approvals: list[dict],
) -> list[dict]:
    if status == "COMPLETED":
        events = []
        if answer_id and answer:
            events = [
                wire(TextMessageStartEvent(message_id=answer_id, role="assistant")),
                wire(TextMessageContentEvent(message_id=answer_id, delta=answer)),
                wire(TextMessageEndEvent(message_id=answer_id)),
            ]
        return [*events, wire(RunFinishedEvent(thread_id=thread_id, run_id=run_id))]
    if status == "FAILED":
        return [wire(RunErrorEvent(message="Agent 执行失败", code=error_code or "RUN_FAILED"))]
    if status == "CANCELLED":
        return [
            wire(
                RunFinishedEvent(
                    thread_id=thread_id, run_id=run_id, outcome=RunFinishedCancelledOutcome()
                )
            )
        ]
    if status == "WAITING":
        interrupts = [
            Interrupt(
                id=item["id"],
                reason="approval",
                message=item.get("title") or "需要审批",
                tool_call_id=item.get("tool_call_id"),
                metadata={"risk": item.get("risk")},
            )
            for item in approvals
            if item.get("status", "PENDING") == "PENDING"
        ]
        return [
            wire(
                RunFinishedEvent(
                    thread_id=thread_id,
                    run_id=run_id,
                    outcome=RunFinishedInterruptOutcome(interrupts=interrupts),
                )
            )
        ]
    return []
