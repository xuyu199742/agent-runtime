# AG-UI 1.0 适配

`GET /api/v1/client/runs/{run_id}/ag-ui/events` 提供经过用户鉴权的 AG-UI 1.0 SSE。原 `/events` 保留；两种客户端可并行使用。新端点从 PostgreSQL `RunTraceEvent`、`Run`、`Message` 和 `Approval` 读取事实，不依赖 Redis 的短期保留窗口。`Last-Event-ID` 或 `?after=` 接受 `sequence:index`，断线后从该事件的下一条续传。`RUN_STARTED` 用于初始化订阅，没有游标 ID。

| 持久事实 | AG-UI 事件 | 说明 |
| --- | --- | --- |
| Run 身份 | `RUN_STARTED` | 每次订阅发送一次 |
| `tool.started` | `TOOL_CALL_START`、`ACTIVITY_SNAPSHOT` | 只暴露工具名、调用 ID 和状态 |
| `tool.completed` / `tool.failed` | `TOOL_CALL_END`、`TOOL_CALL_RESULT`、`ACTIVITY_SNAPSHOT` | 结果用固定摘要，不泄露原始 Tool 输出 |
| `approval.*` | `ACTIVITY_SNAPSHOT` | 审批 ID、状态；等待时还在 `RUN_FINISHED.outcome.interrupts` 给出待审项 |
| `artifact.created` | `ACTIVITY_SNAPSHOT` | 客户端通过原有 Artifact API 读取文件 |
| `effect.*`、Policy/Budget 拒绝 | `ACTIVITY_SNAPSHOT` | 扩展 `activityType=effect/decision`，只含安全摘要 |
| 最终回答 | `TEXT_MESSAGE_START`、`TEXT_MESSAGE_CONTENT`、`TEXT_MESSAGE_END` | 从持久 Message 读取；本版在完成时发送整段文本 delta |
| Run 终态 | `RUN_FINISHED` 或 `RUN_ERROR` | 取消和等待审批使用标准 outcome |

目前 PostgreSQL 不持久化 token 级 `model.delta`，因此 AG-UI 断线恢复使用最终 Message 重建完整回答；AG-UI 通道仅在完成时输出回答文本。需要 token 级实时预览的客户端继续使用原 SSE。不能把 Redis 短期流当作历史事实，也不能用模型输出片段拼接成新的持久日志。`RUN_STARTED` 重发时客户端应保留已收到的同一 Run 内容，按 SSE ID 去重；Activity 应按 `messageId` 覆盖而非追加。

Vue 客户端默认使用原 SSE。设置 `VITE_AGUI_ENABLED=true` 后通过 AG-UI 端点消费消息、工具 Activity、审批与 Artifact 提示；去掉该配置即可回退。Markdown 由 `marked` 解析，再经 DOMPurify 清理后渲染。审批决定、文件读取仍调用已有 REST API。客户端不展示 Tool 参数、原始输出、密钥或隐藏推理。
