class ContextRunError(Exception):
    code = "INTERNAL_ERROR"


class ContextInputTooLarge(ContextRunError):
    code = "CONTEXT_INPUT_TOO_LARGE"


class ContextBudgetExceeded(ContextRunError):
    code = "CONTEXT_BUDGET_EXCEEDED"


class ContextSummaryFailed(ContextRunError):
    code = "CONTEXT_SUMMARY_FAILED"


class RunContextMissing(ContextRunError):
    code = "RUN_CONTEXT_MISSING"


class ContextLeaseLost(Exception):
    """规划结果提交时已不再持有 Run 租约。"""
