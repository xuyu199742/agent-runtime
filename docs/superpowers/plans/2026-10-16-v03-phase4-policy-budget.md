# V0.3 Phase 4：Minimum Policy 与 Execution Budget

## 已核对的代码事实

- 当前 Tool wrapper 登记顺序为 Approval → EffectSafety → ToolError；LangChain 执行时需以集成测试确认外层先执行。
- 只读 ToolExecution 在 `ToolExecutionStore.start` 创建，外部写入在 `EffectStore.prepare` 创建；两处均先锁 Run。
- 外部发送权在 `EffectStore.claim_dispatch` 提交后才允许网络请求。跨 Run 复用不会再次 claim。
- `ModelCallLimitMiddleware.run_model_call_count` 使用 `UntrackedValue`，不能作为 Worker 恢复后的 Run 总预算事实；`ModelExecution` 的 logical `step_id` 更适合作为持久事实。

## 决策

1. Policy 仅看 ExecutionSpec 的 Tool 快照。未知 Tool、未知 effect_type、未授权写入均 DENY；审批在 Policy 后执行。保留 EffectSafety 的最低防线。
2. Agent 增加 `max_tool_calls=30`、`max_external_writes=0`、`max_duration_seconds=3600`。所有新 Run 使用 schema 4，把四项预算和原 Tool 快照一起冻结；v1–v3 沿用旧行为，不读取新 Agent 限额。
3. 不新增 RunUsage。Tool 使用量是本 Run 唯一 ToolExecution 数；外部写入使用量是 `dispatch_run_id` 对应的 EffectRecord 数；模型使用量是本 Run AGENT 阶段的唯一 `step_id` 数。Run 行锁串行化新事实创建与上限检查。
4. 只读 Tool 的调用准入与 ToolExecution 插入同事务；外部写入的 ToolExecution 准入与 Effect `prepare` 同事务；写入额度在 `claim_dispatch` 的同一事务检查。若额度耗尽，已有 PREPARED 保留但不会发送，便于审计和恢复。
5. ModelCallJournal 在 `ModelExecution.start` 之前按 unique step 检查预算；LangChain 的 run_limit 保留为进程内前置保护，但数据库是跨恢复事实源。`CONTEXT_SUMMARY` 不计入。
6. Deadline = Run.created_at + 冻结秒数，包含 WAITING 和恢复停机时间。Run 入口、模型/Tool 准入及发送前均检查；已 DISPATCHED 的请求由 Effect Safety 继续按未知结果核对，不能因 deadline 置为 FAILED。
7. DENY/预算异常为稳定 Run 错误码。仅记录 `policy.denied` 和 `budget.exceeded`；事件与拒绝判断在同一持租约事务内提交，不记录参数正文。

## 实施顺序

### PR 1：Minimum Policy

1. 两项 Phase 3 收尾回归：完整审批拒绝链零 Effect/零请求；同 Run 同 Tool Call 并发重复进入只可一次 dispatch。
2. PolicyDecision 纯逻辑与决策矩阵测试；PolicyMiddleware 在 Approval 前，DENY 不创建 Approval/Effect/ToolExecution。
3. 集成测试确认 wrapper 实际顺序、批准后才进入 Effect；现有只读/Effect 回归。

### PR 2：Execution Budget

1. 迁移 Agent 字段、Admin 输入/输出、ExecutionSpec v4 与旧 schema 兼容；测试冻结值在 Agent 更新后不变。
2. 模型、Tool、外部写入的事务级额度准入与并发/恢复测试；统一稳定错误码和 Timeline。
3. Deadline 的 Run、模型、Tool、发送前及审批恢复检查；测试 WAITING 超时与已发送 Effect 的保守恢复。
4. 隔离数据库迁移、全量 pytest、Ruff、Alembic check；不迁移生产库。
