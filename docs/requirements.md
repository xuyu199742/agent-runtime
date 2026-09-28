# Agent Platform 服务端 V0.1

## 1. 项目目标

从 0 到 1 构建一个 Python-first 的通用 Agent 服务端。

目标不是做一个 Dify 克隆，也不是重新发明 Agent Framework，而是：

> 基于 LangChain + LangGraph 已有能力，构建我们自己的 Agent 产品服务端。

核心要求：

- 架构简单
- 模块边界清楚
- 支持 DB 配置 Agent / Model / Tool
- 支持异步 Run
- 支持流式输出
- 支持断线恢复
- 支持 Tool Calling
- 支持消息消费
- 为后续 RAG / Skill / Memory / Workflow / MCP 留扩展位置
- 不提前实现暂时用不到的复杂能力

---

# 2. 技术路线

第一版只使用 Python。

```text
Python Agent Server
    +
LangChain
    +
LangGraph
    +
PostgreSQL
    +
Redis
```

暂时不要 Go。

未来如果出现：

- 大量 SSE / WebSocket 长连接
- 高并发 Gateway
- 大量任务调度
- 高频消息转发
- 性能瓶颈

再考虑：

```text
Client
   ↓
Go Gateway
   ↓
Python Agent Runtime
```

因此当前架构必须保证以后可以在 Python 外面增加 Go，而不需要重写 Agent 业务。

---

# 3. LangChain / LangGraph / Pi 的定位

## LangChain

直接使用 LangChain 已经成熟的抽象：

```text
ChatModel
Message
Tool
Structured Output
Retriever
Middleware
create_agent()
```

不要重新实现这些已经成熟的基础设施。

---

## LangGraph

作为 Agent Runtime 和以后 Workflow 的基础能力。

优先使用其现有机制：

```text
State
Agent Loop
Streaming
Checkpoint
Persistence
Interrupt
Resume
HITL
Durable Execution
Graph
```

不要重新自己造：

```text
Agent Loop State Machine
Checkpoint Engine
Resume Engine
```

---

## Pi

Pi 不作为代码依赖。

Pi 是架构设计参考。

重点借鉴：

```text
极简 Agent Harness
Context 管理
Tool execution
Streaming Events
Steering
Abort
Compaction
Session 与 Model Context 分离
```

不要移植 Pi Coding Agent。

我们的产品不是 Coding Agent。

---

# 4. 最重要的架构原则

采用类似 Onion Architecture 的思想：

```text
Transport
    ↓
Application
    ↓
Domain

Runtime / Infrastructure
    ↑
通过接口给 Application 使用
```

核心原则：

> 越里面越稳定，越外面越容易替换。

---

# 5. 不要过度抽象 LangChain

不要自己重新定义：

```text
OurMessage
OurBaseTool
OurChatModel
OurRunnable
```

然后再做：

```text
OurXXX <-> LangChainXXX
```

这属于没有价值的包装。

直接使用 LangChain：

```text
BaseMessage
HumanMessage
AIMessage
ToolMessage

BaseTool / @tool

BaseChatModel
```

但是业务 Domain 不直接依赖 LangGraph 的 Graph / Node 等内部概念。

---

# 6. 只保留一个粗粒度 Runtime 接口

Application 不需要知道 LangGraph 内部实现。

可以有：

```python
class AgentRuntime:
    async def run(...)
    async def stream(...)
    async def cancel(...)
```

具体实现：

```text
LangChainAgentRuntime
```

内部：

```text
LangChain create_agent()
        +
LangGraph Runtime
```

不要为 LangChain 每一个类再创建一层 Adapter。

---

# 7. 总体架构

```text
                       Client
                         │
                  HTTP / SSE
                         │
                         ▼
              ┌──────────────────┐
              │    Transport     │
              │     FastAPI      │
              └────────┬─────────┘
                       │
                       ▼
              ┌──────────────────┐
              │   Application    │
              │                  │
              │ Agent Service    │
              │ Chat Service     │
              │ Session Service  │
              │ Run Service      │
              │ Tool Service     │
              └────────┬─────────┘
                       │
             ┌─────────┴─────────┐
             │                   │
             ▼                   ▼
       Agent Runtime           Domain
             │
             ▼
      LangChain Agent
             │
             ▼
        LangGraph
             │
       ┌─────┼─────────┐
       ▼     ▼         ▼
     Model  Tools   Middleware
       │
       ▼
 Infrastructure

 PostgreSQL / Redis / LLM / MCP / Storage
```

---

# 8. Domain 负责什么

Domain 只放我们产品真正拥有的概念。

例如：

```text
AgentDefinition

ModelConfig

ToolDefinition

Session

Message

Run

RunStatus
```

不要把：

```text
LangGraph Node
StateGraph
Checkpoint
Runnable
```

放进 Domain。

这些是框架实现。

---

# 9. AgentDefinition

Agent 配置主要来自 DB。

第一版：

```text
Agent

id
name
description
system_prompt
model_id
max_steps
enabled
created_at
updated_at
```

Agent 与 Tool：

```text
agent_tools

agent_id
tool_id
```

运行时：

```text
DB AgentDefinition
        ↓
Application
        ↓
Agent Factory
        ↓
LangChain create_agent()
```

---

# 10. Model

Model 配置 DB 化。

```text
model_configs

id
name
provider
model_name
base_url
config
enabled
```

需要首先支持：

```text
OpenAI
OpenAI-Compatible
```

因此能够直接支持：

```text
OpenAI
vLLM
Qwen
Bonsai
其他 OpenAI-compatible Server
```

模型能力通过 LangChain Provider 体系接入。

不要自己重新写 Model Protocol。

---

# 11. Tool

Tool 分两个概念：

## Tool Definition

数据库中的配置。

例如：

```text
id
name
description
type
config
enabled
```

第一版支持：

```text
NATIVE
HTTP
```

未来：

```text
MCP
WORKFLOW
REMOTE
```

---

## Tool Runtime

真正执行 Tool。

尽量转换为 LangChain Tool：

```python
@tool
async def xxx(...):
    ...
```

或者：

```python
BaseTool
```

最终统一交给：

```text
create_agent(tools=[...])
```

---

# 12. Middleware

必须利用 LangChain Middleware 机制。

不要把：

```text
Retry
Tracing
Permission
Timeout
Context
Tool Error
```

硬编码进 Agent。

第一版实现我们自己的 Middleware：

```text
TracingMiddleware

ToolErrorMiddleware

RunContextMiddleware
```

未来增加：

```text
PermissionMiddleware

ModelRetryMiddleware

ToolRetryMiddleware

ContextMiddleware

SummarizationMiddleware

HumanApprovalMiddleware

ModelFallbackMiddleware
```

Middleware 是我们未来扩展 Agent 能力的重要机制。

---

# 13. Context

Session 历史和真正发送给模型的 Context 必须逻辑分开。

```text
Session Messages
       ↓
Context Builder
       ↓
Model Context
```

第一版：

```text
System Prompt
+
Conversation History
+
Tool Message
```

未来允许插入：

```text
RAG
Memory
Skill
Compaction
Summary
User Context
```

不要在业务代码里到处：

```python
messages.append(...)
```

Context 构造必须集中管理。

---

# 14. 消息与 Run 必须分开

用户发送消息：

```text
Message
```

Agent 执行：

```text
Run
```

不能把两者混为一个概念。

例如：

```text
Session
  │
  ├── Message
  ├── Message
  ├── Run
  ├── Message
  └── Run
```

---

# 15. 用户发送消息流程

客户端：

```http
POST /api/sessions/{session_id}/messages
```

请求：

```json
{
    "client_message_id": "uuid",
    "content": "帮我分析这个问题"
}
```

服务端：

```text
1. 保存 User Message
2. 创建 Run(PENDING)
3. 投递 Run 到 Redis Stream
4. 返回 message_id + run_id
```

返回：

```json
{
    "message_id": "...",
    "run_id": "..."
}
```

不要让这个 HTTP 请求等待 Agent 执行完成。

---

# 16. Redis 的定位

Redis 从 V0.1 就使用。

但定位必须明确：

> PostgreSQL 管“需要长期记住的东西”。

> Redis 管“当前正在发生的东西”。

---

## Redis 第一版职责

### Run Queue

使用：

```text
Redis Streams
```

例如：

```text
agent:runs
```

Worker 使用 Consumer Group：

```text
agent-workers
```

执行：

```text
XADD
XREADGROUP
XACK
XAUTOCLAIM
```

---

### Event Streaming

运行过程中：

```text
model.delta
tool.started
tool.completed
progress
```

通过 Redis 做实时分发。

---

### Cancellation

例如：

```text
run:{run_id}:cancel
```

用于跨进程停止任务。

---

### Cache

可以缓存：

```text
AgentDefinition
ModelConfig
ToolDefinition
```

但 DB 永远是 Source of Truth。

---

# 17. PostgreSQL 的定位

PostgreSQL 保存：

```text
agents

model_configs

tools

agent_tools

sessions

messages

runs
```

以及真正需要长期追踪的重要执行信息。

Redis 即使全部清空：

```text
用户历史
最终消息
Agent配置
Run最终状态
```

也不能丢。

---

# 18. Run 状态

第一版：

```text
PENDING

RUNNING

COMPLETED

FAILED

CANCELLED

INTERRUPTED
```

不要设计几十种状态。

---

# 19. Worker

API 和 Worker：

```text
同一套代码

同一个 Docker Image
```

但两个 Process Role：

```text
api

worker
```

部署：

```text
api
worker
postgres
redis
```

Worker：

```text
Redis Stream
    ↓
获取 run_id
    ↓
Load Run
    ↓
Load AgentDefinition
    ↓
Build LangChain Agent
    ↓
LangGraph execute
    ↓
Stream Event
    ↓
Persist Result
```

---

# 20. Streaming

客户端订阅：

```http
GET /api/runs/{run_id}/events
```

使用：

```text
SSE
```

事件统一结构：

```json
{
    "type": "model.delta",
    "run_id": "...",
    "sequence": 12,
    "timestamp": "...",
    "data": {}
}
```

第一版事件：

```text
run.started

model.started
model.delta
model.completed

tool.started
tool.completed
tool.failed

run.completed
run.failed
run.cancelled
```

---

# 21. 断线重连

不要把 Run 生命周期绑定 SSE。

正确：

```text
Run
```

后台继续运行。

即使：

```text
浏览器刷新
WiFi断开
SSE断开
```

Run 继续。

优先使用：

```text
LangGraph Persistence / Checkpoint
+
Redis Stream
```

已有机制。

不要自己重新发明 Durable Execution。

客户端保存：

```text
last_sequence
```

重新连接：

```http
GET /api/runs/{run_id}/events?after=12
```

允许：

```text
Replay
+
Live Stream
```

---

# 22. Streaming Event 不全部写 PostgreSQL

尤其：

```text
model.delta
```

不要一个 Token：

```text
INSERT 一次 PostgreSQL
```

实时 delta：

```text
Redis
```

最终完整 AI Message：

```text
PostgreSQL
```

重要状态：

```text
run.completed
run.failed
tool.failed
```

可持久化。

---

# 23. 幂等

客户端必须生成：

```text
client_message_id
```

数据库建立：

```text
UNIQUE(user_id, client_message_id)
```

如果网络重试：

```text
POST
POST
```

不能创建两个 Message / Run。

第二次请求直接返回第一次创建的：

```text
message_id
run_id
```

---

# 24. 消费语义

不要追求 Exactly Once。

采用：

> At-least-once + Idempotency

Redis Stream 消息可能重复消费。

Worker 必须根据：

```text
run_id
run.status
```

保证重复执行安全。

未来有副作用 Tool：

```text
create_order
send_email
delete_xxx
```

必须支持：

```text
idempotency_key
```

---

# 25. Cancel

取消 Run：

```http
POST /api/runs/{run_id}/cancel
```

不要通过关闭 SSE 来取消。

流程：

```text
Client
 ↓
Cancel API
 ↓
Redis cancel flag / signal
 ↓
Worker
 ↓
LangGraph / Agent
 ↓
Cancel
 ↓
Run = CANCELLED
```

---

# 26. LangGraph Persistence

第一版允许直接使用 LangGraph 的：

```text
thread
checkpoint
persistence
interrupt / resume
```

不要我们自己再创建一套重复的：

```text
AgentCheckpointEngine
AgentResumeEngine
```

业务 `Run` 和 LangGraph runtime state 是两个层次。

---

# 27. Workflow

V0.1 不开发可视化 Workflow。

不要现在做：

```text
Workflow Designer
Node Editor
复杂 DAG
```

但是未来 Workflow 优先建立在：

```text
LangGraph StateGraph
```

上。

我们的 DB 最终可以描述业务 Workflow，但这属于后续阶段。

---

# 28. RAG / Skill / Memory

V0.1 不实现。

但架构要保证未来可以：

```text
Agent
  ↓
Middleware / Tool / Retriever
  ↓
RAG

Agent
  ↓
Context Pipeline
  ↓
Memory

Agent
  ↓
Skill Loader
```

扩进去。

不要提前创建大量没有实现的模块。

---

# 29. 推荐工程目录

```text
agent-server/
│
├── app/
│   │
│   ├── domain/
│   │   ├── agent/
│   │   ├── model/
│   │   ├── tool/
│   │   ├── session/
│   │   ├── message/
│   │   └── run/
│   │
│   ├── application/
│   │   ├── agents/
│   │   ├── chat/
│   │   ├── sessions/
│   │   ├── runs/
│   │   └── tools/
│   │
│   ├── runtime/
│   │   └── agent/
│   │       ├── factory.py
│   │       ├── runtime.py
│   │       ├── context.py
│   │       ├── events.py
│   │       └── middleware/
│   │
│   ├── infrastructure/
│   │   ├── database/
│   │   ├── redis/
│   │   ├── llm/
│   │   ├── tools/
│   │   ├── logging/
│   │   └── tracing/
│   │
│   ├── transport/
│   │   ├── http/
│   │   └── sse/
│   │
│   ├── workers/
│   │   └── run_worker.py
│   │
│   └── main.py
│
├── migrations/
├── tests/
│   ├── unit/
│   └── integration/
│
├── docs/
│   └── architecture.md
│
├── pyproject.toml
├── Dockerfile
├── docker-compose.yml
└── README.md
```

不要为了看起来架构高级创建几十个空目录。

只有真正有代码以后再创建模块。

---

# 30. 技术栈

使用：

```text
Python 3.12+

FastAPI

Pydantic v2

SQLAlchemy 2

Alembic

PostgreSQL

Redis
redis-py asyncio
Redis Streams

LangChain

LangGraph

langchain-openai

OpenAI Python SDK

httpx

structlog

pytest
pytest-asyncio

uv
```

---

# 31. 日志

第一版使用：

```text
structlog
```

日志至少带：

```text
request_id

session_id

run_id

user_id

tool_name
```

不要大量 `print()`。

不要把 Python Traceback 直接返回客户端。

---

# 32. Error

统一业务错误：

```text
VALIDATION_ERROR

MODEL_ERROR

TOOL_ERROR

TIMEOUT

CANCELLED

PERMISSION_DENIED

INTERNAL_ERROR
```

Infrastructure 错误转换成这些错误。

客户端不应该知道：

```text
SQLAlchemyError
RedisError
OpenAIError
Python traceback
```

---

# 33. 第一阶段 API

至少实现：

```text
POST   /agents
GET    /agents
GET    /agents/{id}
PUT    /agents/{id}

POST   /models
GET    /models

POST   /tools
GET    /tools

POST   /sessions
GET    /sessions/{id}

POST   /sessions/{id}/messages

GET    /runs/{id}

GET    /runs/{id}/events

POST   /runs/{id}/cancel

GET    /health
```

---

# 34. V0.1 最小测试 Tool

实现：

```text
echo

calculator

http_request
```

然后构建一个测试 Agent：

```text
General Assistant
```

允许模型调用：

```text
calculator
```

完整验证：

```text
User
 ↓
POST Message
 ↓
Run(PENDING)
 ↓
Redis Stream
 ↓
Worker
 ↓
LangChain Agent
 ↓
Model
 ↓
Tool Call
 ↓
Tool Result
 ↓
Model
 ↓
Answer
 ↓
Redis Event Stream
 ↓
SSE
 ↓
Client
```

---

# 35. 必须测试的异常场景

必须至少写测试覆盖：

```text
模型调用失败

Tool 执行失败

Tool 超时

Run 被取消

Redis 短暂不可用

用户重复发送请求

Worker 执行过程中异常

SSE 中途断开

SSE 重新连接

Agent 没有 Tool Call

Agent 连续多次 Tool Call
```

---

# 36. V0.1 明确禁止实现

不要主动加入：

```text
Memory

RAG

Skill

MCP

Multi-Agent

SubAgent

Browser

Computer Use

Sandbox

可视化 Workflow

Temporal

Kafka

RabbitMQ

Celery

Kubernetes

Go Gateway

复杂 RBAC

Agent Version

Config Snapshot

复杂插件系统

复杂 Event Sourcing
```

除非为了当前核心链路无法运行。

---

# 37. 开发阶段

## Phase 1

完成：

```text
FastAPI

PostgreSQL

Redis

Agent CRUD

Model CRUD

Tool CRUD

Session

Message

Run
```

---

## Phase 2

完成：

```text
LangChain Agent Runtime

Agent Factory

OpenAI Compatible Model

Tool Registry

Middleware

Context Builder
```

---

## Phase 3

完成：

```text
Redis Run Queue

Worker

Redis Streams

SSE

Run Cancel

断线恢复

幂等
```

---

## Phase 4

完成完整 Agent 链路：

```text
User
 ↓
Agent
 ↓
Model
 ↓
Tool
 ↓
Model
 ↓
Answer
```

并补齐测试。

完成后 STOP。

不要继续自动开发 RAG、Memory、Workflow 等下一阶段能力。

---

# 38. 架构验收标准

V0.1 完成后必须满足：

### 1

浏览器断开 SSE 后：

```text
Agent Run 继续执行。
```

---

### 2

浏览器重新连接：

```text
可以恢复当前 Run 状态并继续接收事件。
```

---

### 3

API 和 Worker 可以分别启动多个实例。

---

### 4

修改 Agent DB 配置后：

```text
不需要修改 Python Agent 代码。
```

---

### 5

替换：

```text
OpenAI
↓
vLLM OpenAI Compatible
```

不需要修改 Application。

---

### 6

新增 Tool：

```text
不需要修改 Agent Loop。
```

---

### 7

LangChain / LangGraph 代码不能散落在整个项目。

主要集中在：

```text
runtime/
infrastructure/
```

---

### 8

业务 Domain 不依赖：

```text
FastAPI

SQLAlchemy

Redis

LangGraph
```

---

### 9

不能为了架构模式产生大量：

```text
Interface -> Adapter -> Wrapper -> Proxy
```

无意义调用链。

只在真正存在替换边界的位置抽象。

---

# 39. 项目设计原则

开发过程中始终遵守：

> Simple core, extensible edges.

> Prefer composition over framework-specific coupling.

> Use LangChain/LangGraph where they already solve the problem well.

> Do not rebuild proven infrastructure without a concrete reason.

> PostgreSQL stores durable truth. Redis coordinates live execution.

> Agent execution must not depend on the lifetime of an HTTP/SSE connection.

> Build only what V0.1 needs, but do not block future extension.

---

# 40. 最终目标

V0.1 不是要完成整个 Agent Platform。

V0.1 只证明一件事情：

```text
我们的产品架构
       │
       ▼
LangChain / LangGraph Runtime
       │
       ▼
Async Run
       │
       ▼
Redis 消费
       │
       ▼
Model + Tool
       │
       ▼
Streaming
       │
       ▼
可靠地返回给 Client
```

如果这条主链路足够干净、稳定、可测试，再进入：

```text
RAG
Skill
Memory
MCP
Workflow
Multi-Agent
```

下一阶段。