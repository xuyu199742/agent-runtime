# 稳定性与安全收口记录（2026-10-20）

本记录区分本地执行证据与部署前检查。测试环境为本机 PostgreSQL 16、Redis 7 的独立测试库；API/Worker 容器仍是旧镜像，本轮未把它们当作新版本烟测结果。

## 已执行

| 场景 | 命令或方法 | 结果 |
| --- | --- | --- |
| 完整 Python 回归 | 独立测试库 `uv run pytest -q` | 203 passed，约 10 秒；Ruff 与 Alembic check 通过 |
| 长历史 | 500 条历史消息进入 Working Context，摘要输入限制 500 token，保留当前消息 | 单测通过，0.75 秒 |
| 并发 Budget、审批恢复、租约围栏 | 选定 7 个测试连续运行 5 轮 | 35/35 通过，各轮约 1.7 秒 |
| 数据库迁移 | 临时空库 `upgrade head → downgrade -1 → upgrade head → alembic check` | 通过，临时库已删除；降级会删除 Skill 历史，不代表生产有数据时可直接回滚 |
| 客户端依赖 | 升级 Vitest 后 `npm audit --audit-level=moderate` | 0 项公告漏洞；客户端测试及构建通过 |
| AG-UI 断线与权限 | 集成测试验证越权 404、终态文本游标续传 | 通过；持久事实不依赖 Redis 历史 |
| 容器构建与启动 | `docker build -t agent-server:closure-test .`，临时容器连接独立测试库和 Redis，访问 `/ready` | 构建通过，返回 `{"status":"ready"}`；临时容器已停止 |
| 受控写契约 | `pytest tests/integration/test_external_effects.py tests/integration/test_effect_executor.py -q` | 17 passed；使用测试 Provider，未调用真实工单服务 |

## 安全边界复核

- Tool/Skill/MCP 均经过现有 Policy、Budget 和执行记录。Skill 文本与 MCP 返回值属于低信任输入，不能授予新权限；Prompt Injection 仍可能影响模型如何选择已授权 Tool，生产应只绑定必要能力。
- MCP 要求 HTTPS、主机白名单、远端 `readOnlyHint` 与运营白名单；DNS 重绑定仍需出口防火墙约束。远端只读声明需独立审核，不能作为唯一信任依据。
- AG-UI Activity 只发 ID、名称、状态与安全摘要；不发 Tool 参数、原始结果、密钥或隐藏推理。Markdown 在渲染前清理 HTML，禁止图片与嵌入内容加载。
- Worker 捕获异常时只记录异常类型与 Run/Stream ID，避免底层异常消息携带密钥、参数或模型内容进入日志。追查需要使用持久 Timeline、错误码和受控的开发环境复现。

## 部署前仍需执行

1. 对目标环境 PostgreSQL 备份，核对迁移头并执行升级；含真实 Skill/Effect 事实的数据库不要直接降级。
2. 使用真实模型与外部服务做只读 Agent、Skill、MCP、审批、受控写、Activity UI 的端到端烟测。外部工单服务与 MCP Provider 是部署侧资源，本地测试未替代它们。
3. 运行目标环境长时间并发负载，观察 Run 等待时长、租约接管、数据库连接池、Redis 延迟和错误码分布；本轮 5 轮回归与 500 条历史测试不是容量基准。
