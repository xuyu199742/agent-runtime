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

## 2026-09-29 Review 修正后的复验

- `uv run python -m pytest tests -q`：26 passed；含模型密钥入库加密、响应不回显、更新保留/轮换、主密钥缺失时拒绝写入，以及数据库 URL 派生测试。
- `uv run ruff check .`、`uv run ruff format --check .`：通过。
- `uv run alembic check`：No new upgrade operations detected；`agent_migration_test` 执行 `upgrade head → downgrade -1 → upgrade head` 成功。
- 以当前源码直接启动 API、Worker、OpenAI-compatible 测试桩，连接 Docker 中的 PostgreSQL/Redis：Run `e834a88c-4014-432a-bd5e-c049eebeb12c` 经过 calculator 并返回 `答案是 4`；数据库中的模型密钥为密文。Run `7f5ac94e-756d-4b71-b013-4183b52c4aba` 在 SSE 断开时仍为 RUNNING，重连回放至 `run.completed`，最终返回 `答案是 4`。
- 同时启动两个本地 API 实例和两个 Worker；两个 API 的 `/ready` 均返回 200。通过一个 API 提交 Run `5ebf02cf-1ff6-4b2b-ba43-b99a1c2c4128`，从另一个 API 查询得到 `COMPLETED` 与 `答案是 4`；该 Session 只有一条 assistant Message。
- 新的多阶段应用镜像构建成功，镜像大小约 290 MB，原应用镜像约 347 MB。使用该镜像分别启动 API 和 Worker 容器，连接现有 PostgreSQL/Redis 容器；API `/ready` 返回 200，Run `942503d6-3c00-4b60-834d-c78e42f272dc` 实际经过容器 API → Redis Queue → 容器 Worker → 模型测试桩 → calculator → SSE，最终为 `COMPLETED`，回答 `答案是 4`。
- 同一容器镜像下，Run `fde2afdf-b722-4801-815a-2c5902bb5748` 在首个 SSE 事件后断线时仍为 `RUNNING`；以 `after=1` 重连收到后续 Tool 和模型事件，最终为 `COMPLETED`，回答 `答案是 4`。
- Redis Alpine 镜像已拉取并成功执行 `redis-server --version`，本地镜像大小约 39 MB，原 `redis:7` 约 136 MB。PostgreSQL Alpine 镜像尚未完成拉取与现有数据卷兼容性检查；当前容器端到端复验仍使用原 `postgres:16` 和 `redis:7`。

### 原需求第 38 节架构验收复核

| 项目 | 核对结果 |
| --- | --- |
| 1–2. SSE 断线继续、重连恢复 | 本节 Run `7f5ac94e-756d-4b71-b013-4183b52c4aba` 实测。 |
| 3. API/Worker 多实例 | 两个本地 API 和两个 Worker 同时运行；Run `5ebf02cf-1ff6-4b2b-ba43-b99a1c2c4128` 只有一条最终回答。 |
| 4. DB 改 Agent 配置不改代码 | API 管理配置，Worker 每次运行从 DB 读取；配置 CRUD 和 Run 集成测试覆盖。 |
| 5. 替换 OpenAI-compatible 模型不改 Application | 模型工厂只从数据库模型配置构建 `ChatOpenAI`；单元测试和本节本地测试桩覆盖兼容端点。真实 vLLM/Qwen 端点未提供。 |
| 6. 新增 Tool 不改 Agent Loop | Tool 实现各在独立文件，由 registry 映射，Agent Runtime 只接收 LangChain Tool 列表。 |
| 7. LangChain/LangGraph 集中 | 相关导入位于 `app/runtime/`，Worker 入口仅直接使用 PostgreSQL checkpointer。 |
| 8. Domain 不依赖外部框架 | `app/domain/` 的导入扫描确认没有 FastAPI、SQLAlchemy、Redis、LangGraph。 |
| 9. 无多层空包装 | Application 直接组织业务用例，Runtime 只保留 Agent/Tool/Model 组装边界，没有为每个 LangChain 基类再定义一套本地接口。 |
