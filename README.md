# Agent Runtime V0.2（开发中）

V0.2 API 统一使用 `/api/v1`：认证在 `/auth`，用户对话在 `/client`，管理配置在 `/admin`。先运行 `uv run alembic upgrade head`，再运行 `uv run python -m scripts.bootstrap_admin --username admin --display-name 管理员` 创建首个管理员，命令会交互式读取密码。登录取得访问 token 后在请求中传入 `Authorization: Bearer <token>`。访问 token 失效后通过 `/api/v1/auth/refresh` 更新；退出时调用 `/api/v1/auth/logout`。本地接口文档位于 `/docs`。

旧 `/api/*` 默认关闭；仅迁移期可设置 `LEGACY_API_ENABLED=true`。旧接口使用固定开发用户身份，不得对外开放。V0.2 分阶段实施计划见 [docs/v02-implementation-plan.md](docs/v02-implementation-plan.md)。以下 V0.1 说明仅用于旧接口迁移参考。

独立的 Python Agent 服务端。业务配置在 PostgreSQL，异步 Run 和 SSE 实时事件由 Redis Streams 协调，Agent 执行使用 LangChain `create_agent` 与 LangGraph PostgreSQL checkpoint。

## 本地启动

```bash
cp .env.example .env
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 把上一步的输出填入 .env 的 MODEL_SECRET_KEY
docker compose up -d --build
curl http://localhost:8000/ready
```

接口文档：`http://localhost:8000/docs`。`/health` 只检查 API 进程；`/ready` 检查 PostgreSQL 与 Redis。API 与 Worker 共用一个 Dockerfile，使用不同启动命令。PostgreSQL 和 Redis 数据分别保存在 Docker volume 中。

模型名称、端点和模型 API Key 均通过 `/api/models` 写入 PostgreSQL。API Key 在数据库中加密存储，读取接口只返回 `has_api_key`，更新时省略 `api_key` 会保留原值。`MODEL_SECRET_KEY` 是服务加解密主密钥，必须由 API 和 Worker 共用并妥善备份；丢失后已有模型 API Key 无法解密。已有 V0.1 数据库升级后，原来引用环境变量的模型需要通过模型更新接口重新写入 API Key；旧请求字段 `api_key_env` 已移除。使用 OpenAI-compatible 本地服务时，可通过 `base_url` 指向兼容接口，未设置密钥时使用占位值。HTTP Tool 默认关闭，只有服务端 `HTTP_TOOL_ALLOWED_HOSTS` 与 Tool 配置中的 `allowed_hosts` 同时包含目标域名时才启用，并只执行 HTTPS GET。
模型上下文默认最多取最近 30 条消息和约 12000 个 token（保守估算），分别通过 `CONTEXT_MAX_MESSAGES`、`CONTEXT_MAX_TOKENS` 调整；超长的最新消息会截断。完整历史仍保留在 PostgreSQL。

Agent 配置字段 `max_model_calls` 限制单次 Run 的模型调用次数，由 LangChain `ModelCallLimitMiddleware` 执行；旧字段 `max_steps` 已移除。Tool 的 `description` 直接决定模型可见说明，`config.timeout_seconds` 控制超时；HTTP Tool 的 `policy.allowed_hosts` 与服务端 `HTTP_TOOL_ALLOWED_HOSTS` 取交集。

## 发起一次对话

1. `POST /api/models` 创建模型配置。
2. `POST /api/tools` 创建 `calculator`（`type=NATIVE`）。
3. `POST /api/agents` 绑定模型与 Tool。
4. `POST /api/sessions` 创建 Session。
5. `POST /api/sessions/{id}/messages` 发送含 `client_message_id` 的消息，立即得到 `message_id` 和 `run_id`。
6. `GET /api/runs/{id}/events` 订阅 SSE；断线后以 `?after=最后收到的序号` 或 `Last-Event-ID` 继续。
7. `GET /api/runs/{id}` 查询持久状态与最终 `answer`；`POST /api/runs/{id}/cancel` 主动取消。

创建模型时在 JSON 中传入 `api_key`；本地无密钥的兼容服务可省略。示例创建脚本见 [examples/bootstrap_demo.py](examples/bootstrap_demo.py)。完整 API、执行流程和错误语义见 [docs/architecture.md](docs/architecture.md)，队列语义见 [docs/mq-design.md](docs/mq-design.md)。
V0.1 的测试命令与端到端结果见 [docs/verification.md](docs/verification.md)。

## 开发和测试

```bash
uv sync --group dev
docker compose up -d postgres redis
uv run alembic upgrade head
docker compose exec -T postgres createdb -U agent agent_test
DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:5434/agent_test uv run alembic upgrade head
TEST_DATABASE_URL=postgresql+asyncpg://agent:agent@localhost:5434/agent_test \
TEST_CHECKPOINT_DATABASE_URL=postgresql://agent:agent@localhost:5434/agent_test \
TEST_REDIS_URL=redis://localhost:6380/1 \
uv run python -m pytest tests -q
uv run ruff check .
uv run ruff format --check .
```

`tests/support/openai_stub.py` 是本地端到端测试桩，可用 `uv run uvicorn openai_stub:app --app-dir tests/support --host 0.0.0.0 --port 18001` 启动；Docker 内模型 `base_url` 设为 `http://host.docker.internal:18001/v1`。真实模型烟测需要自行提供可用端点和凭证。

## 部署边界

V0.1 采用固定的本地开发 `user_id`，没有登录、租户隔离和公网访问控制。**不要直接暴露到公网。** `client_message_id` 在同一用户下唯一，重复提交返回原 `message_id/run_id`。同一 Session 一次只允许一个活跃 Run。

Redis 事件流在 Run 终态后保留 24 小时；超期重连返回 410，客户端应读取 `GET /api/runs/{id}`。PostgreSQL 保存最终回答与状态，Redis 清空不影响长期数据。Redis Streams 至少一次交付，内置 Tool 无业务副作用；未来新增写操作 Tool 时须使用基于 `run_id + tool_call_id` 的稳定 `idempotency_key`，由目标业务系统去重。Worker 默认同时执行最多 10 个 Run（`WORKER_CONCURRENCY`）；租约丢失、心跳异常、取消或关机均终止旧执行，崩溃后的消息由 XAUTOCLAIM 重新领取并从 checkpoint 恢复。终态 Run 的 checkpoint 默认 24 小时后清理（`CHECKPOINT_RETENTION_HOURS`）。已发出的外部 Tool 请求无法由租约失效撤回。
