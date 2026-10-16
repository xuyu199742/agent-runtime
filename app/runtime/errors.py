from app.context.errors import ContextRunError


class ToolResultUnavailable(ContextRunError):
    """Tool 已成功，但持久记录不足以安全重放结果。"""

    code = "TOOL_RESULT_UNAVAILABLE"


class ApprovalRecoveryLost(ContextRunError):
    """审批已到达等待边界，但恢复所需检查点不存在。"""

    code = "APPROVAL_RECOVERY_LOST"


class EffectIdempotencyConflictError(ContextRunError):
    """同一业务键解析到不同的写入请求。"""

    code = "EFFECT_IDEMPOTENCY_CONFLICT"


class EffectUncertain(ContextRunError):
    """外部请求结果未能确认，禁止交回模型继续执行。"""

    code = "EFFECT_UNCERTAIN"


class EffectManualRequired(ContextRunError):
    """自动核对无法得出最终结论。"""

    code = "EFFECT_MANUAL_REQUIRED"


class EffectResultUnavailable(ContextRunError):
    """已成功的 Effect 缺少可安全重放的规范结果。"""

    code = "EFFECT_RESULT_UNAVAILABLE"


class EffectNotApplied(ContextRunError):
    """Provider 已证明请求未产生目标副作用。"""

    code = "EFFECT_NOT_APPLIED"


class WriteNotAllowed(ContextRunError):
    """写入 Tool 缺少显式受控 Provider。"""

    code = "WRITE_NOT_ALLOWED"
