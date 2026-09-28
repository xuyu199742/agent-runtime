# Agent Platform 服务端 V0.1 实施计划

依据：[完整需求说明](requirements.md)。本计划只覆盖 V0.1，须经用户确认后开始编码。按 Phase 1→4 顺序执行，每阶段完成测试并报告结果后再进入下一阶段。

## 一、先固定的设计边界

- 项目位于 `/Users/bruce/code/agent-server`，与 HotGo 完全分离，使用独立 Git 仓库。
- Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、Redis Streams、LangChain、LangGraph、uv。API 与 Worker 使用同一镜像的不同进程角色。
- Domain 只表达业务实体和状态；FastAPI、SQLAlchemy、Redis、LangChain/LangGraph 分别留在 transport、infrastructure、runtime。Application 通过一个粗粒度 `AgentRuntime` 边界发起执行，不包装 LangChain 的每个基础类。
- PostgreSQL 存 Agent/Model/Tool 配置、Session、Message、Run、最终回答和重要错误。Redis 存待消费 Run、运行中事件与取消信号。LangGraph PostgreSQL checkpointer 只保存图的执行状态，不能代替 SSE 事件回放；回放由 Redis 的逐 Run Stream 提供。
- HTTP 建立 Message 和 Run 后立即返回；SSE 是独立连接。断开 SSE 不取消 Run。`after` 和 `Last-Event-ID` 统一映射事件序号，重连先回放再跟随实时事件。
- 默认只实现无副作用 Native Tool。HTTP Tool 只允许受配置约束的 GET、拒绝内网与本机地址并控制重定向；其目标范围需要在启用前明确。任何有副作用 Tool 必须另行定义幂等键。
- 不建立空的未来模块，不加入 RAG、Memory、Skill、MCP、Workflow、Go 网关或管理界面。

## 二、代码文件职责（按需创建）

| 路径 | 职责 |
| --- | --- |
| `app/domain/entities.py`, `app/domain/errors.py` | 业务概念、Run 状态与错误码；不依赖框架 |
| `app/infrastructure/database/models.py`, `session.py` | ORM 映射和异步连接 |
| `app/application/catalog.py`, `chat.py`, `runs.py` | 配置管理、消息提交、Run 查询与取消 |
| `app/transport/http.py`, `sse.py`, `schemas.py` | API、输入输出校验、SSE 协议 |
| `app/runtime/factory.py`, `context.py`, `agent.py` | 模型和 Tool 组装、历史上下文、LangChain Agent 执行 |
| `app/runtime/middleware.py` | Tracing、Tool Error、Run Context 中间件 |
| `app/infrastructure/redis_queue.py`, `events.py` | 消费组、事件流、取消信号 |
| `app/worker.py` | Run 抢占、执行、恢复与 ACK |
| `migrations/versions/*.py` | 显式迁移，禁止运行时自动建表 |
| `tests/unit/`, `tests/integration/` | 单元、数据库/Redis/服务联调测试 |
| `Dockerfile`, `docker-compose.yml`, `README.md` | 本地部署和操作说明 |

按功能实际增长调整文件拆分，不预先铺设几十个空目录。所有代码注释与说明默认中文。

## Phase 1：独立服务和持久业务数据

### 实施顺序

1. 建立 `pyproject.toml`、uv lock、格式与测试配置、Docker Compose（API、Worker、PostgreSQL、Redis）、环境变量示例、健康检查和结构化日志。
2. 建 Alembic 首次迁移：`model_configs`、`tools`、`agents`、`agent_tools`、`sessions`、`messages`、`runs`。配置表设外键/索引；Message 增加 `UNIQUE(user_id, client_message_id)`；Run 关联触发消息并记录状态、时间、错误与最终回答关联。
3. 实现配置 CRUD、Session 创建和查询、Message/Run 创建与查询。请求校验拒绝禁用的 Agent/Model/Tool 和无效关联。敏感模型凭证仅存环境变量或密钥引用，API 不回显。
4. 消息提交在单个 DB 事务内同时创建 Message 与 PENDING Run。此阶段不执行 Agent；Redis 连通性可检查，但入队放到 Phase 3。

### 阶段测试与通过条件

- `uv run pytest tests/unit tests/integration/phase1` 和迁移升级/降级测试通过。
- 同一个 `(user_id, client_message_id)` 并发重试只得到同一对 `message_id/run_id`。
- CRUD、无效配置、外键约束、错误码、数据库重启后的数据保留均验证。
- API/Worker 镜像可分别启动；`/health` 只表示进程存活，`/ready` 检查依赖。

## Phase 2：LangChain/LangGraph Runtime

### 实施顺序

1. 用 DB 中的 AgentDefinition、ModelConfig 和 ToolDefinition 构建 `create_agent()`；模型接 `langchain-openai`，支持 OpenAI 与自定义 OpenAI-compatible `base_url`。模型凭证不能写入日志。
2. Tool Registry 把 DB 定义映射为 LangChain Tool；先实现 `echo`、`calculator`，再实现受限制的 `http_request`。参数 Schema、超时、错误映射集中在 Tool 层。
3. Context Builder 在一处组织 system prompt、Session 历史和当前消息。会话历史与模型上下文保持逻辑分离，避免把全部历史无界传给模型；限制与截断规则写成明确配置。
4. 接 LangChain Middleware：TracingMiddleware、ToolErrorMiddleware、RunContextMiddleware。LangGraph 使用 PostgreSQL checkpointer，业务 Run ID 与 checkpoint thread ID 建立稳定映射。
5. 实现 `AgentRuntime` 的流式接口与取消钩子；Application 不直接使用 Graph/Node。

### 阶段测试与通过条件

- 使用假模型验证无 Tool、单次 Tool、连续 Tool Call 和 max_steps 限制；不依赖外部模型额度。
- 验证 Tool 失败/超时、模型失败被归类为稳定业务错误；日志包含 request_id、session_id、run_id、user_id、tool_name 且不泄露凭证。
- 重建 Runtime 后可从 PostgreSQL checkpoint 读取执行状态；Domain 依赖扫描不出现 FastAPI、SQLAlchemy、Redis、LangGraph。
- 替换 OpenAI-compatible 模型配置无需修改 Application 代码。

## Phase 3：异步消费、SSE 和恢复

### 实施顺序

1. 在 Message/Run 事务提交后向 Redis `agent:runs` 投递 `run_id`。针对「DB 已提交、Redis 投递失败」增加 PENDING Run 定期补投；补投产生重复队列项也由 DB 状态抢占化解。
2. Worker 建立 Consumer Group，使用 XREADGROUP 消费、XACK 确认、XAUTOCLAIM 认领超时消息。通过数据库原子条件更新把 PENDING Run 抢占为 RUNNING；运行中记录租约/心跳，进程异常后按明确超时策略重新领取，利用 checkpoint 恢复。避免两个 Worker 同时执行同一 Run。
3. Worker 将 `run.started`、model/tool 事件、终态事件写入每个 Run 的 Redis Stream。事件含 `type/run_id/sequence/timestamp/data`，序号单调递增；终态和完整 AI Message 写入 PostgreSQL。Redis Stream 保留期与重连超期响应写入 API 契约。
4. `GET /runs/{id}/events?after=N` 先回放 `N` 之后的事件，随后持续读取。SSE 断开只结束订阅；Run 仍由 Worker 执行。终态后关闭 SSE，并提供 GET Run 查询最终状态。
5. `POST /runs/{id}/cancel` 对 PENDING Run 直接落库为 CANCELLED；对 RUNNING Run 写入取消信号，Worker 在流式边界检查并终止。明确取消与完成竞争时唯一终态的写入规则。

### 阶段测试与通过条件

- Redis 暂时不可用后，PENDING Run 可补投；重复投递不造成重复终态；Worker 崩溃后消息可认领。
- SSE 断开时 Run 继续；按 `after` 重连无重复、无漏读；两个 API/Worker 实例共享队列和事件。
- 取消 PENDING/RUNNING Run、终态竞争、Redis 事件过期、无事件新连接均有测试。
- 不在 PostgreSQL 为每个 `model.delta` 写一行；最终回答和终态在 Redis 清空后仍可查询。

## Phase 4：完整链路与验收

### 实施顺序

1. 生成本地测试 Agent（General Assistant）和 `calculator` Tool 的示例配置，不把测试数据自动写入生产数据库。
2. 跑完整链路：Message → PENDING Run → Redis Queue → Worker → Agent/Model → Tool → 模型最终回答 → PostgreSQL → Redis Events → SSE。
3. 补齐需求说明第 35 节全部异常场景；使用假模型保证自动化测试稳定，再用真实 OpenAI-compatible 模型做一次手动烟测（仅在提供凭证时）。
4. 检查需求说明第 38 节九条架构验收项，记录测试命令和结果；更新 README 中的启动、配置、API 调用和故障恢复说明。
5. 提交 V0.1 代码并停止，不自动进入 RAG/Skill/Memory/MCP/Workflow。

### 最终通过条件

- 四阶段测试与迁移检查全部通过，完整链路可重复演示。
- 浏览器断线重连可回放尚在保留期的事件，Run 与 SSE 生命周期独立。
- 多实例下一个 Run 只有一个活跃执行者；重复客户端请求和重复队列消息安全。
- 无认证的开发版不能作为公网生产服务。生产发布另行确定认证/授权与出站 Tool 策略。

## 计划确认时需确定的两项约定

1. 原说明要求 `UNIQUE(user_id, client_message_id)`，但未定义用户认证。建议 V0.1 先采用配置固定的本地开发 `user_id`，API 不接受客户端任意指定；真正多用户和权限在 V0.1 后设计。
2. 说明要求 `http_request` Tool，但没有允许访问的目标范围。建议 V0.1 默认禁用，仅通过服务端显式域名白名单启用，并限制为 GET。

若用户确认本计划而未调整上述两项，即按建议值实施。
