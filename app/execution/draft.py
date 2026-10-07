from dataclasses import dataclass


@dataclass(frozen=True)
class ExecutionSpecDraft:
    agent_id: str
    agent_revision: int
    schema_version: int
    runtime_version: str
    snapshot: dict
