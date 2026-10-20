# 最小端到端示例

先启动 API、Worker、PostgreSQL 与 Redis，完成迁移及管理员初始化，并提供可用的模型端点。以下示例的创建操作会写入当前服务数据库，建议先在测试环境运行。

## 只读 Agent + Skill

```bash
export AGENT_MODEL_NAME=实际模型名
export AGENT_MODEL_BASE_URL=https://兼容接口/v1  # 使用 OpenAI 官方端点时可省略
export AGENT_MODEL_API_KEY=模型密钥
uv run python examples/bootstrap_demo.py
```

脚本提示输入管理员密码，登录 V1 管理 API，创建模型、`calculator`、只读 Skill 和 Agent，打印 ID。Skill 的 `references/guide.md` 只在模型调用 `skill.read` 时读取。若运营侧已配置只读 MCP Provider，可同时设置 `AGENT_MCP_PROVIDER_ID` 与 `AGENT_MCP_REMOTE_NAME`；脚本会先发现，再把 MCP Tool 加入同一个 Agent。Provider 白名单和凭据设置见 [MCP 说明](mcp-readonly.md)。

用客户端登录后选择新 Agent 发送消息；也可调用 `POST /api/v1/client/conversations`（`{"agent_id":"..."}`），再调用 `POST /api/v1/client/conversations/{id}/messages`（`{"client_message_id":"唯一值","content":"请读取运行说明并计算 2+2"}`）。返回的 Run ID 可用于订阅 `/api/v1/client/runs/{id}/events` 或 `/api/v1/client/runs/{id}/ag-ui/events`。客户端设置 `VITE_AGUI_ENABLED=true` 后展示工具 Activity、审批卡、文件和 Markdown；默认 SSE 仍提供实时文本预览。

## 受控写 Agent

`ticket.create` 是唯一已登记的受控写示例。Admin Tool API 有意只接受 `READ_ONLY`，因此需要按 [Effect Safety 启用范围](v03-external-effect-safety.md) 在受控部署流程中写入 Tool 配置，并给 Worker 配置 `TICKET_SERVICE_BASE_URL`、`TICKET_SERVICE_TOKEN`。将该 Tool 绑定 Agent，设置 `max_external_writes=1`，发起创建工单请求后在客户端审批卡决定。外部服务必须满足稳定业务键、幂等写入与核对接口契约；未知结果会进入 `MANUAL_REQUIRED`，不会自动重发。

无需真实外部工单服务也可运行契约测试：

```bash
uv run pytest tests/integration/test_external_effects.py tests/integration/test_effect_executor.py -q
```

这些测试覆盖提交、重复请求、断线核对和人工处理边界。真实服务接入前，仍须用该服务验证幂等作用域、查询可见性和出口网络策略。
