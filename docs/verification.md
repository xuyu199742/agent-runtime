# V0.1 验证记录

验证日期：2026-09-29（Asia/Shanghai）。

## 自动化与迁移

```text
uv run ruff check .                         All checks passed!
uv run ruff format --check .                所有文件格式符合要求
uv run python -m pytest tests -q            22 passed
uv run alembic check                        No new upgrade operations detected.
```

测试使用独立的 `agent_test` PostgreSQL 数据库和 Redis DB 1。Alembic 在 `agent_migration_test` 上完成 `upgrade head → downgrade -1 → upgrade head`。LangGraph 的 `checkpoint_*` 表由其 checkpointer 管理，Alembic 比对明确忽略这些表。

自动化用例覆盖：模型失败、Tool 失败与超时转换、执行中和待执行取消、Redis 入队失败后的 PENDING Run 补投、客户端重复请求、Worker 执行异常、SSE 序号回放及事件过期、无 Tool Call、单次和多次 Tool Call、队列未 ACK 消息重新认领、LangGraph checkpoint 恢复、双 Worker 抢占，以及 Redis 事件清除后 PostgreSQL 最终回答仍可查询。

## Docker 端到端

- `docker compose up -d --build --scale worker=2`：API、两个 Worker、PostgreSQL、Redis 均启动；`GET /ready` 返回 `{"status":"ready"}`。
- 额外启动一个无对外端口的 API 实例，其容器内 `GET /ready` 返回相同结果，验证 API 实例可并行连接同一 DB/Redis。
- 使用 `tests/support/openai_stub.py` 模拟 OpenAI-compatible 流式接口，实际经过 Docker API → PostgreSQL → Redis Queue → Worker → ChatOpenAI → calculator → ChatOpenAI → Redis Events → SSE。Run `7eb79c2c-16ec-4aa3-9fda-e6591f91edb7` 在 SSE 断开时为 `RUNNING`，随后变为 `COMPLETED`，回答 `答案是 4`；以最后序号重连返回 200 和 `tool.completed` 等后续事件。
- Run `b4bd0358-75fe-4900-bcb1-a48cfdab0199` 的 Redis 事件手动删除后，`GET /api/runs/{id}` 仍从 PostgreSQL 返回 `COMPLETED` 与 `答案是 4`。
- Run `76791fef-79a7-41e0-b0f4-37b1408af117` 在 `RUNNING` 时调用取消接口，最终为 `CANCELLED`。
- 最终镜像重建后，Run `9843e048-b910-4396-8fcd-4a6b39569198` 再次完成并返回 `答案是 4`。
- Worker 日志包含 `request_id`、`session_id`、`run_id` 和 `user_id`，不包含模型凭证。

## 未在本机验证的边界

没有提供真实模型凭证，因此未对 OpenAI、vLLM 或 Qwen 的真实服务执行烟测；OpenAI-compatible 协议通过本地测试服务验证。V0.1 为单用户本地开发版，公网部署需要先补认证、租户授权和正式的 Tool 出站网络限制。外部有副作用 Tool 不在本版范围内，其恰好一次执行不作保证。
