# MCP 只读 Provider

MCP V1 通过官方 Python SDK 的 Streamable HTTP 客户端接入。部署时配置 `MCP_ALLOWED_HOSTS`（逗号分隔的主机名）及 `MCP_PROVIDERS`（JSON 对象）。示例：

```dotenv
MCP_ALLOWED_HOSTS=mcp.example.com
MCP_PROVIDERS={"search":{"url":"https://mcp.example.com/mcp","token":"通过密钥管理器注入","read_only_tools":["search"]}}
```

凭据仅保存在部署配置中，不进入 ToolDefinition 或 ExecutionSpec。Provider ID、URL、远端 Tool 名称及输入 schema 会随 ToolDefinition 冻结进新 Run 的 ExecutionSpec；恢复时若 Provider 地址变化，调用失败，不转向新地址。密钥可以在原地址轮换。

管理员可通过 `GET /api/v1/admin/tools/mcp/discover/{provider_id}` 查看已授权且远端声明 `readOnlyHint=true` 的 Tool，再用原有 Tool 创建接口配置 `type=MCP`、`config.provider_id`、`config.remote_name` 和可选 `timeout_seconds`。服务端在创建或更新时重新发现并保存 schema，拒绝客户端自报的 schema 和地址。MCP Tool 始终是 `READ_ONLY`，执行继续经过现有 Policy、Approval、Budget、ToolExecution 和 Timeline。写 Tool 不开放；未来只有可信幂等和核对契约接入 Effect Safety 后才能考虑。

连接要求 HTTPS、显式主机白名单且禁止 IP 字面量、URL 凭据、跨源重定向。每次调用重查 Provider 身份、运营白名单、远端只读声明和冻结 schema；参数按 JSON Schema 2020-12 校验。单次调用超时不超过 30 秒，文本结果不超过 32 KiB，非文本结果拒绝。SDK 连接仅在单次发现或调用中存活，断网不会改变其他 Run 的持久事实。

主机白名单无法单独阻止 DNS 重绑定，生产环境仍需在出口防火墙限制 MCP 服务 IP 段。`readOnlyHint` 是远端声明，运营白名单应只包含经过信任审查的真正只读操作。部署配置中的 Token 属于服务级凭据；本版不做最终用户委托授权。
