const recoveryErrors: Record<string, string> = {
  APPROVAL_RECOVERY_LOST:
    "审批所需的执行检查点已丢失，本次运行已安全停止。请联系管理员核对记录。",
  TOOL_RESULT_UNAVAILABLE:
    "已完成的工具调用缺少可重放结果，本次运行已安全停止。请联系管理员核对结果。",
  REASONING_CONTEXT_MISSING: "旧任务缺少推理上下文，请重新发起任务。",
  CANCELLED: "本次执行已停止。如需继续，请先核对本次运行记录。",
};

export function runErrorText(code: string | null): string {
  if (!code) return "本次执行没有完成。";
  return (
    recoveryErrors[code] ||
    `执行失败（${code}）。请核对运行记录后再发起新请求。`
  );
}
