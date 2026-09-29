# Agent Runtime V0.1 架构重构验收

验收日期：2026-09-29。

## 目录与依赖

```text
app/
  domain/          业务状态、模型/工具定义、对话消息
  application/     Agent 配置、Session 与消息提交规则
  persistence/     SQLAlchemy ORM、数据库会话、粗粒度 Repository
  messaging/       Redis 客户端、Run Queue、SSE 事件
  runtime/         LangChain Agent、Context、Model、Tool、Checkpoint
  transport/http/  FastAPI 路由与 SSE
  worker/          runner、consumer、retention、进程入口
```

Domain 不依赖框架；Application 不导入 SQLAlchemy、Redis、LangChain/LangGraph 或 ORM；Runtime 不导入 ORM。架构导入测试覆盖这些边界。迁移保留现有业务表数据：`agents.max_steps` 改名为 `max_model_calls`，`runs` 增加 checkpoint 清理时间，`tools` 增加实际参与 HTTP 域名白名单构建的 `policy`。

## 运行机制

- Worker 使用 `asyncio.TaskGroup` 管理消费者及后台扫描；消费者先取得 semaphore 空槽，才从 Redis Stream 领取一条消息。`WORKER_CONCURRENCY` 默认 10，单条消息失败不会结束消费者。
- 每个 Run 的 Agent 与租约心跳处于同一个执行范围。租约失效、心跳异常、Redis 协调失败或 Worker 关闭时停止旧 Agent，并保留未 ACK 消息。显式取消写入 `CANCELLED`。最终提交要求 DB 中的 owner 匹配且租约仍有效；失效 Worker 不能续租或提交回答。
- Worker crash 后，`RUNNING` Run 保持原业务状态；租约过期后由 Redis `XAUTOCLAIM` 与 DB 条件更新认领，使用 `thread_id = run_id` 从 LangGraph checkpoint 继续。Session 历史仍保存在 PostgreSQL Message。
- 每个并发 Run 使用独立 `AsyncPostgresSaver`，共享官方支持的 `psycopg.AsyncConnectionPool`（最大连接数为并发数加 2）。Serializer 使用受限 msgpack 配置。终态 Run 超过 `CHECKPOINT_RETENTION_HOURS`（默认 24）后调用 `adelete_thread`，清理标记独立于业务更新时间。
- `max_model_calls` 使用 LangChain `ModelCallLimitMiddleware`；图 `recursion_limit` 仅为安全上限。Context 同时受消息数和近似 token 预算限制；Tool 的 DB 描述、超时和 HTTP policy 实际参与 LangChain Tool 构造。
- Redis 事件流负责 SSE 实时输出与序号回放，LangGraph checkpoint 负责执行恢复。二者职责独立；PostgreSQL 保存最终 Run 与回答。API 的 Redis 客户端由 FastAPI lifespan 管理。

## 自动化与迁移

```text
TEST_DATABASE_URL=... TEST_CHECKPOINT_DATABASE_URL=... TEST_REDIS_URL=... uv run pytest tests -q
47 passed

uv run ruff check .
All checks passed!

uv run ruff format --check .
93 files already formatted

alembic downgrade -2 → upgrade head → alembic check
No new upgrade operations detected.
```

测试包含：消息幂等、Run 抢占与租约 fencing、两个 Run 并发、单 Run 失败后的消费者存活、心跳异常/租约丢失/Redis 异常/Worker 关闭后的旧执行停止、Worker crash 后 XAUTOCLAIM 与 checkpoint resume、四个并发 Run 的 PostgreSQL checkpointer、模型调用上限、Tool 失败与超时、模型失败、Pending/Running 取消、SSE 断线回放与事件过期、Redis 入队失败后补投，以及 checkpoint retention。

## Docker Compose 与真实链路

- `docker compose up -d --build --scale worker=2` 成功；`postgres:16-alpine`、`redis:7-alpine`、API 与两个 Worker 正常运行；`GET /ready` 返回 200。
- 本地 OpenAI-compatible 流式测试服务作为模型端点。通过容器 API 提交两条 Run `0f2ebebb-06e9-4c17-b33a-d68882cb5fe7`、`9bdcc75e-13fb-415f-8267-83a26ca6657d`，均经过 PostgreSQL → Redis Queue → Worker → ChatOpenAI → calculator → ChatOpenAI → PostgreSQL/Redis Events，最终 `COMPLETED`、回答 `答案是 4`。
- 第一条 Run 在首个 SSE 事件后断线时仍为 `RUNNING`；带 `after` 重连收到 `tool.completed` 等后续事件直至 `run.completed`。
- 容器中 Run `51d555cc-240a-47ce-98ab-80df87da8a84` 的 RUNNING 取消最终为 `CANCELLED`；停掉两个 Worker 后创建的 Run `54b43b7f-1f6f-4ed5-ae29-47cb728e7628` 在 PENDING 时取消，最终为 `CANCELLED`。两个 Worker 已重新启动。

## 已知限制

- 使用本地 OpenAI-compatible 测试服务验收；没有真实 OpenAI、vLLM 或 Qwen 凭证/端点。
- Context token 数为保守估算，尚未使用模型专属 tokenizer；没有自动摘要或 compaction。
- 当前 Tool 无业务写入副作用。Tool Registry 已预留 `tool_idempotency_key(run_id, tool_call_id)`；未来写入型 Tool 必须将该键交给目标系统去重。租约失效无法撤回已经发出的外部请求。
- V0.1 没有 Human Approval 的 `interrupt()` / `Command(resume=...)` API；当前 resume 指 Worker 故障后的继续执行。
- Redis 事件只保留终态后 24 小时；过期后客户端读取 PostgreSQL 的 Run 最终状态。服务仍是本地单用户开发版，没有公网认证与租户隔离。
