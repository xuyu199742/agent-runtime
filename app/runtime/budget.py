"""执行预算的稳定错误与 Run 墙钟截止时间。"""

from datetime import UTC, datetime, timedelta

from app.context.errors import ContextRunError


class BudgetLimitExceeded(ContextRunError):
    code = "BUDGET_EXCEEDED"
    dimension = "unknown"

    def __init__(self, limit: int, used: int):
        super().__init__(f"{self.dimension} 预算已耗尽")
        self.limit = limit
        self.used = used

    def event_data(self) -> dict:
        return {"dimension": self.dimension, "limit": self.limit, "used": self.used}


class BudgetModelCallsExceeded(BudgetLimitExceeded):
    code = "BUDGET_MODEL_CALLS_EXCEEDED"
    dimension = "model_calls"


class BudgetToolCallsExceeded(BudgetLimitExceeded):
    code = "BUDGET_TOOL_CALLS_EXCEEDED"
    dimension = "tool_calls"


class BudgetExternalWritesExceeded(BudgetLimitExceeded):
    code = "BUDGET_EXTERNAL_WRITES_EXCEEDED"
    dimension = "external_writes"


class RunDeadlineExceeded(ContextRunError):
    code = "RUN_DEADLINE_EXCEEDED"

    def __init__(self, deadline_at: datetime, now: datetime):
        super().__init__("Run 执行截止时间已到")
        self.deadline_at = deadline_at
        self.now = now

    def event_data(self) -> dict:
        return {
            "dimension": "deadline",
            "deadline_at": self.deadline_at.isoformat(),
            "now": self.now.isoformat(),
        }


def check_deadline(created_at: datetime, max_duration_seconds: int) -> None:
    if created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    deadline_at = created_at + timedelta(seconds=max_duration_seconds)
    now = datetime.now(UTC)
    if now >= deadline_at:
        raise RunDeadlineExceeded(deadline_at, now)
