from app import persistence
from app.persistence.database import Run, RunTraceEvent


def test_run_local_sequence_and_model_execution_schema_exist():
    assert hasattr(Run, "trace_sequence")
    assert hasattr(RunTraceEvent, "sequence")
    assert hasattr(persistence.database, "ModelExecution")
