# Agent Runtime

独立 Python Agent 服务端。PostgreSQL 保存配置、Run、执行事实和 LangGraph checkpoint；Redis Streams 协调任务、取消与实时 SSE。Agent 执行基于 LangChain `create_agent`。用户接口、管理接口统一位于 `/api/v1`，旧 `/api/*` 默认关闭。

## 本地启动

```bash
cp .env.example .env
uv run python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# 将生成值填入 .env 的 MODEL_SECRET_KEY
docker compose up -d --build
curl http://localhost:8000/ready
uv run python -m scripts.bootstrap_admin --username admin --display-name 管理员
```

首次管理员命令会交互读取密码。API 文档在 `http://localhost:8000/docs`；`/health` 检查进程，`/ready` 检查 PostgreSQL 和 Redis。管理后台位于 `web/admin`，用户客户端位于 `web/client`；各自执行 `npm ci && npm run dev`。模型 API Key 经 `MODEL_SECRET_KEY` 加密保存，API 与 Worker 必须共用这把密钥并妥善备份。

## 当前能力

- 用户登录、会话、异步 Run、取消、审批和 Artifact；管理端配置 Agent、模型、Tool 和 Skill。
- 新 Run 冻结 ExecutionSpec；模型调用、工具调用、Budget、Effect、Working Context 和时间线写入持久事实。Run 恢复沿用冻结快照与 LangGraph checkpoint。
- Skill 是版本化只读 Context Source，正文与 `references/` 资源由 `skill.read` 按需读取。[Skill 说明](docs/skill-v1.md)
- MCP V1 仅允许显式白名单内的只读 Streamable HTTP Tool；部署端管理 Provider 凭据。[MCP 说明](docs/mcp-readonly.md)
- 原 SSE 提供实时增量；AG-UI 1.0 端点从持久事实重建执行活动与最终回答。[AG-UI 映射及边界](docs/ag-ui-adapter.md)

`GET /api/v1/client/runs/{id}/events` 是默认实时流；`GET /api/v1/client/runs/{id}/ag-ui/events` 是 AG-UI 适配流。两者均需 Bearer Token。AG-UI 客户端可设置 `VITE_AGUI_ENABLED=true`，默认保留旧 SSE。旧 `/api/*` 仅可在本地迁移期通过 `LEGACY_API_ENABLED=true` 开启，使用固定开发用户身份，不得对外开放。

## 开发验证

```bash
uv sync --group dev
docker compose up -d postgres redis
uv run alembic upgrade head
uv run pytest -q
uv run ruff check .
uv run ruff format --check .
cd web/client && npm ci && npm test && npm run build && npm run format:check
```

集成测试需要独立测试库及 `TEST_DATABASE_URL`、`TEST_CHECKPOINT_DATABASE_URL`、`TEST_REDIS_URL`；数据库先执行 `alembic upgrade head`。迁移前备份 PostgreSQL。回滚 Skill 迁移会删除 Skill 历史，具体边界见 [Skill 说明](docs/skill-v1.md)。外部写入的幂等与人工核对边界见 [Effect Safety](docs/v03-external-effect-safety.md)。

更多运行时设计与历史决策见 [架构说明](docs/architecture.md)、[V0.2 契约](docs/v02-runtime-contract.md)、[上下文规划](docs/v03-context-planning.md)、[执行时间线](docs/v03-execution-timeline.md) 和 [可靠性边界](docs/v03-reliability-boundaries.md)。
