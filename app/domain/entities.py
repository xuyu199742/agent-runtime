from enum import StrEnum


class RunStatus(StrEnum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    INTERRUPTED = "INTERRUPTED"


_ALLOWED = {
    RunStatus.PENDING: {RunStatus.RUNNING, RunStatus.CANCELLED},
    RunStatus.RUNNING: {
        RunStatus.COMPLETED,
        RunStatus.FAILED,
        RunStatus.CANCELLED,
        RunStatus.INTERRUPTED,
    },
    RunStatus.INTERRUPTED: {RunStatus.RUNNING, RunStatus.CANCELLED},
}


def can_transition(current: RunStatus, target: RunStatus) -> bool:
    return target in _ALLOWED.get(current, set())
