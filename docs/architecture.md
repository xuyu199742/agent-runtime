# 架构与运行契约

## 边界

`transport` 负责 HTTP、Pydantic 和 SSE；`application` 负责业务用例；`domain` 保存业务状态与错误概念；`runtime` 集中 LangChain/LangGraph、模型与 Tool 组装；`infrastructure` 管数据库、Redis 和日志。Domain 不依赖 FastAPI、SQLAlchemy、Redis 或 LangGraph。Application 使用粗粒度 Runtime 调用，不包装 LangChain 的基础类。

业务 Run 和 LangGraph thread 是不同层次。一个 Run 使用同 ID 的 checkpoint thread；Session 历史存 PostgreSQL，Context Builder 选取最近消息作为模型输入。系统提示词由 Agent 配置传给 `create_agent`，本次 ToolMessage 留在 LangGraph 执行状态里。

## 消息和 Run

提交消息时，数据库事务创建 user Message 与 PENDING Run。`UNIQUE(user_id, client_message_id)` 保证同一个客户端消息幂等；Session 行锁让不同消息不能同时创建两个活跃 Run。事务提交后 API 投递 Redis Stream `agent:runs` 并立即返回；投递失败时 Worker 定期扫描 PENDING Run 补投。

Worker 通过 Consumer Group 读取，使用条件更新抢占 PENDING 或租约过期的 RUNNING Run；重复消息不能同时执行。运行期间刷新租约。崩溃后其他 Worker 用 XAUTOCLAIM 认领，尝试从 LangGraph checkpoint 恢复。只有成功持有租约的 Worker 能写入最终状态与回答。Redis 队列使用至少一次交付；当前 Native Tool 仅执行无业务副作用操作。

## 事件、断线和取消

Worker 向逐 Run Redis Stream 发布 `run.started`、`model.started/delta/completed`、`tool.started/completed/failed` 和终态事件。序号单调递增，SSE `after` 回放序号之后的事件并继续等待新事件。SSE 连接断开不影响 Worker。终态事件流保留 24 小时；超出保留期返回 410。最终 AI Message、Run 终态和错误码存 PostgreSQL，`GET /api/runs/{id}` 提供持久状态与回答。

取消 PENDING Run 时直接写数据库终态；取消 RUNNING Run 时写 Redis 取消信号，Worker 在执行过程中检查并终止，最终状态仍由持有租约的 Worker 原子写入。关闭 SSE 不会取消 Run。

## 错误与安全

API 返回稳定的错误码（例如 `VALIDATION_ERROR`、`MODEL_ERROR`、`TIMEOUT`、`CANCELLED`、`PERMISSION_DENIED`、`INTERNAL_ERROR`），不返回数据库异常或 Python traceback。模型凭证从环境变量读取，不进入模型配置响应。HTTP Tool 只允许服务端和 Tool 双白名单交集内的 HTTPS GET，拒绝非公网解析地址且不跟随重定向；公网部署前仍需正式的出站网络限制。

本版只支持本地单用户开发。RAG、Memory、Skill、MCP、Workflow、可视化和 Go 网关均不在 V0.1 中。

## 依赖接口参考

- [LangChain `create_agent` API](https://reference.langchain.com/python/langchain/agents/factory/create_agent)
- [LangGraph PostgreSQL 异步 Checkpointer](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver)
- [Redis Streams 与 Consumer Group](https://redis.io/docs/latest/develop/data-types/streams/)
