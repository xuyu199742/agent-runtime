# V0.3 Phase 3 外部写入安全

## 启用范围

当前仅支持代码注册的 `ticket.create` 示例。Admin Tool API 仍只接受 `READ_ONLY`。受控写入需要直接配置数据库中的 Tool，并在 Run 创建时冻结为 ExecutionSpec schema 3；必须包含：

```json
{
  "name": "ticket.create",
  "type": "NATIVE",
  "effect_type": "EXTERNAL_WRITE",
  "policy": {"write_allowed": true, "requires_approval": true},
  "config": {
    "effect_contract": {
      "operation_name": "ticket.create",
      "provider_namespace": "实际外部账户的稳定标识",
      "contract_version": 1
    }
  }
}
```

Worker 还需设置 `TICKET_SERVICE_BASE_URL`（HTTPS）和 `TICKET_SERVICE_TOKEN`。示例服务契约为：

- `POST /tickets`：请求体含 `ticket_key`、`title`，`Idempotency-Key` 请求头是 `ticket:create:<ticket_key>`；成功响应包含 `ticket_id`。
- `GET /tickets/by-idempotency-key/<URL 编码的幂等键>`：找到后响应包含 `ticket_id`。404 只表示暂时查不到，不能证明写入不会稍后落地。

部署前必须验证服务端对幂等键的去重作用域与 `provider_namespace` 一致，并验证查询接口对已提交请求的可见性。未设置外部服务配置时，Worker 在执行写入 Run 前报配置错误。

## 状态与恢复

`PREPARED` 表示尚未取得发送权；`DISPATCHED` 表示已在数据库认领发送权，实际请求可能已发出。恢复者对 `DISPATCHED` 只核对。核对成功进入 `SUCCEEDED` 并保存规范结果；查不到或暂时失败不能自动重发，进入 `MANUAL_REQUIRED`。只有服务端能够证明原请求已终止、且未来不会生效时，`NOT_APPLIED(final=true)` 才能进入 `FAILED`。当前 HTTP 示例不会产生这种证明。

`EffectRecord` 按 `(provider_namespace, operation_name, business_key)` 唯一。相同键、相同规范请求可跨 Run 复用；相同键、不同请求返回 `EFFECT_IDEMPOTENCY_CONFLICT`。`ToolExecution` 记录每次模型 Tool Call，并通过 `effect_id` 关联业务效果。Run Timeline 中的 Effect 事件与 Effect 状态在同一数据库事务落库。

Admin Retry 会拒绝原 Run 中未定案的写入。`MANUAL_REQUIRED` 当前没有人工裁决接口，需要运维查看外部服务与数据库记录后处理；不能通过重试绕过。管理端 `GET /api/v1/admin/runs/{run_id}/tool-executions` 在 `run:view` 权限下提供 Effect 当前状态、业务键哈希、外部引用和错误码，不返回业务请求体。

跨 Run 保证以稳定、可信的业务键为前提。若模型在 Retry 中更换 `ticket_key`，Runtime 无法判断两个键是否指向同一业务动作。生产接入应由可信上游提供该键，不能仅依赖模型自由生成。

## 迁移与回滚

迁移 `f6d2a4c0e19b` 新增 `effect_records` 和可空的 `tool_executions.effect_id`。旧 ToolExecution 行保持空关联。先部署数据库迁移，再启用 schema 3 写入 Run。回滚应用前应停止新写入并确认没有未定案 Effect；降级迁移会删除 Effect 历史和关联，不应在有真实外部写入后直接执行。当前自动化测试只对独立 `agent_test` 数据库运行迁移。
