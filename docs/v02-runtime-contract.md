# Runtime V0.2 执行契约

## 配置冻结

消息提交时，Message、Run 与 ExecutionSpec 在同一 PostgreSQL 事务中创建。ExecutionSpec 保存 Agent revision、Prompt 与哈希、模型配置、加密后的模型密钥、Tool 配置和 Context 限额。Worker 首次执行和 checkpoint 恢复都读取这份快照；历史 V0.1 Run 没有快照时，仍按旧配置路径恢复。Admin 的 ExecutionSpec 查询会移除密钥密文。

Agent 每次编辑递增 revision 并写入完整 AgentRevision。迁移会把升级前的现有 Agent 配置回填为 revision 1。已存在 Run 的配置不随 Agent 编辑变化。

## Tool 执行

ToolExecution 写入真实 Tool 调用路径，以 `(run_id, tool_call_id)` 唯一标识逻辑调用，保存参数哈希、effect type、稳定 idempotency key、attempt、状态和结果。恢复时若已记录完成结果，直接返回该结果。未完成的调用会增加 attempt 并重新执行。V0.2 仅提供 `READ_ONLY` Tool 实现；将来添加写操作时，目标业务系统必须按 idempotency key 去重。Worker 租约丢失不能撤回已发出的外部请求，也不能单靠本地记录保证外部操作恰好一次。

`failure_policy=RETURN_ERROR` 把 Tool 错误返回给模型；`FAIL_RUN` 让 Run 失败。Admin Tool Test 复用实际 Tool Factory、超时和安全策略，只允许无需审批的只读 Tool。

## Approval 与恢复

Tool policy 可设置 `requires_approval=true`。LangGraph interrupt 将 Run 置为 `WAITING`，Approval 在 PostgreSQL 持久化，Worker 释放租约并确认队列消息。批准或拒绝后，数据库事务将 Approval 决策与 Run 的 `PENDING` 状态一起提交；Worker 从同一个 `thread_id=run_id` checkpoint 恢复。拒绝会向模型返回 Tool 错误，Tool 本身不执行。`WAITING` 只表示等待人工决策，Worker crash 仍使用 RUNNING 租约过期与 XAUTOCLAIM 恢复。WAITING Run 可以取消，未决 Approval 会一并取消。

## Retry

仅 `FAILED` Run 可 Retry。Retry 创建新 Run，保留原 Run 的失败终态，并设置 `parent_run_id`、`attempt`、`origin=RETRY`。新 Run 复用原 Message 与 ExecutionSpec，拥有独立的 `thread_id` 和 checkpoint。Admin Agent Test 同样走创建 Conversation、Run、Queue、Worker 的完整路径，标记 `origin=ADMIN_TEST`。

## 验证

- `ruff check .`、`ruff format --check .`、完整 pytest 通过。
- 独立 PostgreSQL 数据库验证迁移升级、回滚、再升级，并验证旧 Agent revision 回填。
- Docker 双 Worker E2E 验证模型 Tool 调用、Approval WAITING/批准/恢复、SSE、ToolExecution、Agent Test、Revision、Worker ID 和 Retry lineage。
