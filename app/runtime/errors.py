from app.context.errors import ContextRunError


class ToolResultUnavailable(ContextRunError):
    """Tool 已成功，但持久记录不足以安全重放结果。"""

    code = "TOOL_RESULT_UNAVAILABLE"


class ApprovalRecoveryLost(ContextRunError):
    """审批已到达等待边界，但恢复所需检查点不存在。"""

    code = "APPROVAL_RECOVERY_LOST"
