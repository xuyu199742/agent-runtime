# 架构与运行契约

## 边界

`transport` 负责 HTTP、Pydantic 和 SSE；`application` 负责业务规则；`domain` 保存业务状态与错误；`runtime` 集中 LangChain/LangGraph、模型、Context 与 Tool 组装；`persistence` 集中 SQLAlchemy 和粗粒度 Repository；`messaging` 集中 Redis Queue、事件与共享客户端；`worker` 分为 Run 执行范围、消费循环、checkpoint 清理与进程入口。Domain 不依赖框架，Application 不直接导入 ORM、SQLAlchemy 或 Redis。没有重新定义 LangChain 的基础类。

业务 Run 和 LangGraph thread 是不同层次。一个 Run 使用同 ID 的 checkpoint thread；Session 历史存 PostgreSQL，Context Builder 同时按消息数和近似 token 预算选取模型输入。系统提示词由 Agent 配置传给 `create_agent`，本次 ToolMessage 留在 LangGraph 执行状态里。

服务只配置一个 `DATABASE_URL`：SQLAlchemy 使用其 `asyncpg` 驱动；LangGraph checkpointer 从同一 URL 派生 `psycopg` 驱动 URL。二者连接同一 PostgreSQL 数据库。

## 消息和 Run

提交消息时，数据库事务创建 user Message 与 PENDING Run。`UNIQUE(user_id, client_message_id)` 保证同一个客户端消息幂等；Session 行锁让不同消息不能同时创建两个活跃 Run。事务提交后 API 投递 Redis Stream `agent:runs` 并立即返回；投递失败时 Worker 定期扫描 PENDING Run 补投。

Worker 通过 Consumer Group 读取，只有空闲执行槽时才取下一条消息；`asyncio.TaskGroup` 和 semaphore 将每进程并发限制为 `WORKER_CONCURRENCY`。条件更新抢占 PENDING 或租约过期的 RUNNING Run。Agent、租约心跳和取消监听属于同一执行范围：心跳失败、租约失效、Redis 协调失败或进程关闭会停止 Agent，消息保持未 ACK；显式取消则写入 CANCELLED。崩溃后其他 Worker 用 XAUTOCLAIM 认领，从 LangGraph checkpoint 恢复。最终提交还须满足未过期租约且 owner 匹配，防止两个 Worker 都提交回答。Redis 队列使用至少一次交付。

每个并发 Run 使用独立的 `AsyncPostgresSaver` 实例，共用官方支持的 `psycopg.AsyncConnectionPool`；严格 msgpack serializer 禁止不受控 Python 对象反序列化。终态 Run 超过 `CHECKPOINT_RETENTION_HOURS` 后调用 saver 的 `adelete_thread`，再标记清理时间。Agent 使用 `ModelCallLimitMiddleware` 限制 `max_model_calls`，图递归上限仅作安全保险。

## 事件、断线和取消

Worker 向逐 Run Redis Stream 发布 `run.started`、`model.started/delta/completed`、`tool.started/completed/failed` 和终态事件。序号单调递增，SSE `after` 回放序号之后的事件并继续等待新事件。SSE 连接断开不影响 Worker。终态事件流保留 24 小时；超出保留期返回 410。最终 AI Message、Run 终态和错误码存 PostgreSQL，`GET /api/runs/{id}` 提供持久状态与回答。

取消 PENDING Run 时直接写数据库终态；取消 RUNNING Run 时写 Redis 取消信号，Worker 在执行过程中检查并终止，最终状态仍由持有租约的 Worker 原子写入。关闭 SSE 不会取消 Run。API 的 Redis 客户端与连接池在 FastAPI lifespan 中创建和关闭。

## 错误与安全

API 返回稳定的错误码（例如 `VALIDATION_ERROR`、`MODEL_ERROR`、`TIMEOUT`、`CANCELLED`、`PERMISSION_DENIED`、`INTERNAL_ERROR`），不返回数据库异常或 Python traceback。模型配置与加密后的 API Key 存 PostgreSQL；模型配置响应只显示是否已有密钥。`MODEL_SECRET_KEY` 仅作为服务主密钥，不存模型配置，API/Worker 必须使用同一个值。HTTP Tool 只允许服务端和 Tool 双白名单交集内的 HTTPS GET，拒绝非公网解析地址且不跟随重定向；公网部署前仍需正式的出站网络限制。

当前 Tool factory 把数据库定义与代码实现组合：描述、超时和 HTTP 域名 policy 均参与生成最终 LangChain Tool。内置 Tool 无业务写入副作用；Runtime Tool Registry 提供 `tool_idempotency_key(run_id, tool_call_id)`。未来写入型 Tool 必须从运行上下文取这两个 ID，传给目标系统按键去重。租约取消无法撤回已发出的外部请求。

本版只支持本地单用户开发。RAG、Memory、Skill、MCP、Workflow、可视化和 Go 网关均不在 V0.1 中。

## 依赖接口参考

- [LangChain `create_agent` API](https://reference.langchain.com/python/langchain/agents/factory/create_agent)
- [LangGraph PostgreSQL 异步 Checkpointer](https://reference.langchain.com/python/langgraph.checkpoint.postgres/aio/AsyncPostgresSaver)
- [Redis Streams 与 Consumer Group](https://redis.io/docs/latest/develop/data-types/streams/)
