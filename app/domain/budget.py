"""Agent 级执行限额的单一默认值和冻结形状。"""

from dataclasses import dataclass

DEFAULT_MAX_MODEL_CALLS = 10
DEFAULT_MAX_TOOL_CALLS = 30
DEFAULT_MAX_EXTERNAL_WRITES = 0
DEFAULT_MAX_DURATION_SECONDS = 3600


@dataclass(frozen=True)
class ExecutionBudget:
    max_model_calls: int
    max_tool_calls: int
    max_external_writes: int
    max_duration_seconds: int

    @classmethod
    def from_snapshot(cls, values: dict) -> "ExecutionBudget":
        budget = cls(**values)
        for name, minimum in (
            ("max_model_calls", 1),
            ("max_tool_calls", 1),
            ("max_external_writes", 0),
            ("max_duration_seconds", 1),
        ):
            value = getattr(budget, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
                raise ValueError(f"ExecutionBudget.{name} 无效")
        return budget

    def snapshot(self) -> dict:
        return {
            "max_model_calls": self.max_model_calls,
            "max_tool_calls": self.max_tool_calls,
            "max_external_writes": self.max_external_writes,
            "max_duration_seconds": self.max_duration_seconds,
        }
