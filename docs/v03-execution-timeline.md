# V0.3 PR2：持久执行时间线

每个 Run 在 PostgreSQL 中分配从 1 开始的 `trace_sequence`。过程事件只有在 Run 仍为 `RUNNING`、Worker 持有有效租约时才能分配序号；终态事件与 Run 状态更新在同一事务提交。时间线按 `(run_id, sequence)` 唯一，旧事件在迁移时按原始 `id` 顺序回填。

模型调用写入 `ModelExecution`。Agent 模型调用由 LangChain middleware 记录；上下文摘要直接在 Worker 的摘要调用处记录为 `CONTEXT_SUMMARY`，不消耗 Agent 的 `max_model_calls`。同一个逻辑步骤在恢复时重新调用模型会递增模型调用的 `attempt`，旧的未完成调用标记为 `ABANDONED`。`Run.attempt` 仍表示 Run 重试次数。模型事实在 middleware 返回、LangGraph 写 checkpoint 之前提交；两者使用独立连接，无法形成一个数据库事务。

`ToolExecutionStore.finish` 将 Tool 结果及其时间线引用一起提交；`ApprovalRepository.ensure` 将审批及其时间线引用一起提交。Redis 只负责即时事件与增量文本。PostgreSQL 的时间线及事实可在 Redis 事件或已完成 Run 的 checkpoint 清除后查询，但无法凭时间线恢复执行中的 Run。

管理员通过 `GET /api/v1/admin/runs/{run_id}/timeline` 分页查询序号、事件类型、步骤尝试次数、事实引用、耗时与摘要。`GET /api/v1/admin/model-executions/{id}` 才返回单次模型调用的白名单输入与输出；两者都要求 `run:view` 权限。模型序列化只保留角色、文本、Tool 调用、用量与结束原因，不保存 provider 原始响应、`reasoning_content` 或 `additional_kwargs`。`model.delta` 仍只存在于有保留期限的 Redis 事件中。

租约失效后，旧 Worker 不得再写入模型、Tool、审批或过程时间线。已经发出的外部 Tool 请求无法撤回，后续有副作用 Tool 必须以稳定 `idempotency_key` 在目标系统去重。
