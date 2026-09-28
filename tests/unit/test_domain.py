from app.domain.entities import RunStatus, can_transition


def test_run_terminal_state_cannot_transition():
    assert can_transition(RunStatus.PENDING, RunStatus.RUNNING)
    assert can_transition(RunStatus.RUNNING, RunStatus.CANCELLED)
    assert not can_transition(RunStatus.COMPLETED, RunStatus.RUNNING)
    assert not can_transition(RunStatus.CANCELLED, RunStatus.COMPLETED)
