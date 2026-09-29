# Agent Runtime V0.1 重构实施计划

目标：锁定可维护的 Runtime、持久化与消息边界，完成 Worker 并发及故障恢复验证。本轮不增加产品能力。

## 当前架构问题

- `app/worker.py` 串行消费；租约监督异常时 Agent 可能继续执行。
- 多个 Run 共用 `AsyncPostgresSaver.from_conn_string` 的单连接。
- Application 直接使用 SQLAlchemy ORM；`INTERRUPTED` 状态残留。
- `max_steps` 被换算为图递归限制；Tool 描述未按数据库配置生效；Context 只按条数截取。
- checkpoint 缺少清理策略。

## 目标目录与代码处置

- 保留 `domain/`、`application/`、`runtime/`、`transport/http/`；将 ORM 与数据库会话移至 `persistence/`，Redis Queue/Event/Cancel 移至 `messaging/`，Worker 拆为执行范围和消费循环。
- 删除 Application 中的 SQLAlchemy 查询、`INTERRUPTED` 分支及 `max_steps` 递归换算。
- 移动现有 ORM、Redis 实现，保持 Alembic 表结构兼容；仅在字段确实变化时增加迁移。
- 重写 Worker 执行监督和有界并发；使用官方 `AsyncPostgresSaver(AsyncConnectionPool)`。
- 重写 Tool 工厂入口，让 DB 描述、超时和配置参与构建；Context Builder 同时限制条数与近似 token 数。

## 执行顺序及验证

1. 先增加租约失效、心跳异常和关闭取消测试；实现统一 Run execution scope。运行 Worker 单元及集成测试。
2. 增加多 Run 并发、背压和同 Run 双 Worker 测试；实现有界消费；换用 PostgreSQL checkpointer 连接池并验证并发 checkpoint。
3. 移除 `INTERRUPTED`，使用模型调用次数 Middleware；验证 crash/checkpoint resume、Pending/Running cancel。
4. 建立粗粒度持久化边界并调整 Application；增加架构导入检查，保持现有 API 与迁移兼容。
5. 完成 Tool/Context 配置及 checkpoint retention，测试失败分类、Redis 临时不可用、SSE replay/过期。
6. 运行全量 unit/integration、Alembic 升降迁移、Docker Compose 和完整 E2E；记录结果与限制，冻结 V0.1。

`thread_id = run_id`；PostgreSQL Message 保存 Session 历史，LangGraph checkpoint 仅保存单次 Run 执行状态。未来有副作用 Tool 的接口预留 `idempotency_key`，调用方必须保证幂等。
