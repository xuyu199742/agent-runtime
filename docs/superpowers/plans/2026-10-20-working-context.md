# Run 内 Working Context 实施计划

> **For agentic workers:** 本计划分 P1-A、P1-B 两个顺序 PR；逐项验证后再进入下一项。当前只完成设计，不启动 Skill、MCP、AG-UI。

**目标：** 每次 Agent 模型调用前控制 Working Context 的大小，保留原始执行事实，并在 Worker 崩溃或租约接管后复用已提交的压缩结果。

**架构：** 以 `create_agent` 的 `abefore_model` 作为规划入口，使用其默认 `messages` reducer 更新 LangGraph 工作视图。PostgreSQL 的原始消息、ModelExecution、ToolExecution、EffectRecord、Timeline、Artifact 仍是事实；`ModelExecution` 中 `CONTEXT_SUMMARY` 的完成结果是摘要调用的持久结果，checkpoint 是可恢复的 Working Context 视图。第一版不新增压缩表。

**技术栈：** Python 3.12、LangChain 1.4.2、LangGraph 1.2.12、PostgreSQL、现有 fenced PostgresSaver、pytest。

---

## 评审结论与前置条件

- **ACCEPT WITH CHANGES。** 文档对主线预算缺失的判断正确；预算已通过面向 `master` 的 PR #13 重新提出，165 项测试、迁移往返与 CI 已通过。P1-B 应从 #13 合并后的主线开始；P1-A 仅包含纯规划逻辑，可独立评审。
- 现有 `RunContextSnapshot` 只冻结首次模型调用前的会话上下文；`app/worker/context_planning.py` 不处理 Run 内 Tool/Model 循环。
- 官方 `SummarizationMiddleware` 支持 `abefore_model` 和安全的 AI/Tool 消息边界，也会用 `RemoveMessage` 更新图状态；但其摘要调用没有接入本项目 `ModelExecution`，只统计消息 token，且摘要输入超大时可能返回固定文本。第一版借鉴其 hook/reducer，不直接接入该中间件。
- 现有 `LeaseFencedPostgresSaver` 已把 checkpoint 写入与 Run 租约检查放在同一事务。P1-B 仍须通过故障注入证明压缩状态与模型调用之间的 checkpoint 顺序。
- 当前 `ExecutionSpec v4` 没有 Working Context 策略版本。新 Run 应使用 v5 冻结 `working_context.strategy_version=1`；v1–v4 保持原恢复语义，避免部署后旧 Run 被新算法重规划。v5 继续复用已有 `context_budget` 数值，不另建阈值 DSL。

## 代码映射与改动边界

| 位置 | 当前职责 | 计划改动 |
| --- | --- | --- |
| `app/context/budget.py`、`tokens.py` | 冻结阈值与近似 token 估算 | 复用，无新 tokenizer |
| `app/context/planner.py` | 初始 Conversation Context | 保持不变，避免混合两种摘要作用域 |
| `app/context/working.py` | 尚不存在 | 纯函数：压力估算、可压缩边界、消息合法性、确定性替换计划 |
| `app/runtime/working_context.py` | 尚不存在 | `abefore_model` 适配；读取冻结预算和事实引用；摘要调用与重放 |
| `app/runtime/agent.py` | `create_agent` 中间件注册 | 仅对 schema v5 注册 Working Context middleware；不改写 graph |
| `app/worker/model_recording.py`、`app/persistence/repositories/traces.py` | 模型调用 durable journal | 增加“查询已完成摘要 step”的小接口；复用 `CONTEXT_SUMMARY` phase |
| `app/worker/runner.py` | 装配 Runtime 与 checkpoint | 注入冻结策略；图执行使用 `durability="sync"`，验证后固定 |
| `app/application/execution_spec.py`、`app/execution/config.py` | Run 快照/解析 | 新 Run schema v5；旧 schema 兼容；无数据库 schema 迁移 |
| `tests/unit/test_working_context.py` | 尚不存在 | 纯规划、合法性和硬限单测 |
| `tests/integration/test_working_context.py` | 尚不存在 | Tool loop、租约、checkpoint、审批/Effect 恢复故障注入 |

## 冻结配置与输入估算

新 Run 的 `ExecutionSpec.snapshot` 保持现有 `model`、`tools`、`context_policy`、`context_budget`、`execution_budget`，另加：

```json
{"working_context": {"strategy_version": 1, "recent_complete_turns": 1}}
```

每次模型调用前估算 `system + tool_schema + messages + output_reserve + safety_margin`；前四项中的 system、tool schema、output reserve 与 margin 直接来自冻结快照，消息使用 `approximate_tokens`。`context_budget.soft_limit/hard_limit` 已扣除固定开销，规划器只比较消息部分。对同一调用再次规划须得到同样的源内容哈希和选择结果。

保护集：当前用户消息、最近一个完整交互、尚未得到全部 ToolMessage 的 AI tool-call batch、等待审批或结果未定的 Effect。完整交互以消息关系界定，不按任意字符位置截断。若保护集本身超过 hard limit，抛出 `CONTEXT_BUDGET_EXCEEDED`，不得改写当前输入或 Tool 参数。

软阈值以上先替换较旧、较长、已完成且存在 `ToolExecution` 事实的 ToolMessage 内容为短引用，保留原 `tool_call_id` 和对应 AI tool-call。引用包含 `ToolExecution.id`、输出哈希和可定位的 Artifact ID；原结果仍在 PostgreSQL。仍超阈值时，对较旧的完整交互生成结构化摘要：任务目标、已验证事实、关键决策与约束、完成/未完成事项、事实引用、下一步。摘要提示明确禁止把模型猜测写作已验证事实。若压缩后仍超 hard limit，稳定失败；不无限重复调用摘要模型。

## 持久化与重放契约

1. `abefore_model` 从 checkpoint 的 `messages` 和冻结 ExecutionSpec 产生确定性候选；源哈希覆盖消息 ID、角色、正文、Tool Call ID/参数、冻结策略版本。
2. 需要模型摘要时，logical step ID 使用 `run_id + graph_step + source_hash`；先查询同一 step 已完成的 `ModelExecution(phase=CONTEXT_SUMMARY)`。存在且输入哈希一致时直接复用摘要；不一致则以稳定上下文一致性错误终止。
3. 无已完成结果时，沿用 `ModelCallJournal.start/complete`，模型响应及 usage 先落库，再向 `abefore_model` 返回 reducer 更新。摘要调用不计入 Agent `max_model_calls`，但受 Run deadline、摘要输入预算与冻结的每次压缩轮数约束；整个 Run 的轮数上界为 `max_model_calls × max_compaction_rounds`。
4. Reducer 更新为 `RemoveMessage(REMOVE_ALL_MESSAGES) + 新摘要/引用消息 + 完整保留尾部`。ToolMessage 只与对应 AI tool-call 一起保留；对未决 Tool batch 不做压缩。
5. 后续模型节点开始前必须已持久化更新后的 checkpoint。P1-B 用 `durability="sync"` 和故障注入证明这一顺序；现有 Saver 继续做租约围栏。checkpoint 已含结果时不再重做摘要；checkpoint 尚未含结果时以源哈希复用完成的摘要调用。
6. `RunContextSnapshot` 仍只负责首次输入，恢复时不读最新 Session、Agent 或 Tool 配置。Working Context 不写回该快照、不重写 ToolExecution/EffectRecord。

### Crash window 与风险矩阵

| 位置/风险 | 可见 durable 状态 | 恢复行为与验收 |
| --- | --- | --- |
| 摘要请求前 Worker 失租 | 无新摘要结果 | 租约围栏拒绝旧 Worker 提交；新 Worker 从原 checkpoint 规划 |
| 摘要模型已返回、`ModelExecution.complete` 前崩溃 | STARTED/ABANDONED 尝试，无可信结果 | 可再次调用摘要；保留 attempt 与 usage 可追查，不能把未提交文本注入模型 |
| 摘要结果已提交、checkpoint 前崩溃 | 完成的 `CONTEXT_SUMMARY`，旧 checkpoint | 以同一 step/source hash 复用结果，不再次摘要，不读取最新 Session |
| checkpoint 已提交、Agent 模型前崩溃 | checkpoint 含压缩视图 | 恢复图状态，跳过该 step 的压缩；Agent 模型预算仍按 durable logical step 判断 |
| 压缩时失租或旧 Worker 补写 | 租约转移 | journal completion 与 fenced Saver 都拒绝旧 Worker；只有新持租约者继续 |
| Tool batch/审批中断/Effect 未定 | 待处理完整消息与独立 Effect 事实 | 不压缩未决 batch；恢复不从摘要路径重放 Tool 或 Provider 调用 |
| 单个受保护大结果或估算过低 | 已持久 Tool 事实，模型输入无法安全容纳 | 优先事实引用；仍超限返回 `CONTEXT_BUDGET_EXCEEDED`。Provider context overflow 只做一次受控分类后终止，不循环重试 |
| 摘要模型捏造或输出格式无效 | 原始事实未改 | 校验结构化字段和引用；无效输出返回 `CONTEXT_SUMMARY_FAILED`，不覆盖 checkpoint |

## PR 拆分与验收

### P1-A：纯 Working Context planner

文件：`app/context/working.py`、`tests/unit/test_working_context.py`。提供 `WorkingPlan`、`plan_working_context(messages, frozen_budget, protected_ids, fact_refs)`、`validate_tool_pairs(messages)`；只产出确定性 `KEEP/REFERENCE/SUMMARIZE/FAIL` 计划，不调用模型/数据库。单测覆盖软/硬阈值、system 与当前用户输入保护、完整 AI/Tool batch、旧 Tool 引用、无法压缩的大结果、同输入同哈希。此 PR 无 migration、无 Runtime 行为变化。

### P1-B：Runtime 接入与恢复

文件：`app/runtime/working_context.py`、`app/runtime/agent.py`、`app/worker/runner.py`、`app/worker/model_recording.py`、`app/persistence/repositories/traces.py`、`app/application/execution_spec.py`、`app/execution/config.py`、`tests/integration/test_working_context.py`。按上面的 durable 契约实现 schema v5、摘要重放、checkpoint 同步与稳定错误；不新增表。先用 Fake Chat Model 验证连续 Tool 结果增长与压缩后的下一轮模型输入，再用故障注入覆盖矩阵所有崩溃窗口。隔离 PostgreSQL/Redis 全量 `uv run pytest -q`、`uv run ruff check .`、`uv run ruff format --check .`、`alembic check`；PR 正文附实际命令和结果。

## 明确不做

不新增 `WorkingContextSnapshot`/CompactionRecord 双事实源，不覆盖初始 `RunContextSnapshot`，不重写 `create_agent` 或 LangGraph checkpoint，不引入另一个 Event Journal、Policy Engine、成本计费、模型原生 opaque compaction、Skill/MCP/AG-UI。若 P1-B 故障测试证明 `ModelExecution + checkpoint` 无法保持选定视图一致，再单独评审最薄的 compaction 记录表及唯一键，而不是预先建表。

## 依据

- [LangChain short-term memory：`before_model`、`RemoveMessage`、消息合法性和内置摘要](https://docs.langchain.com/oss/python/langchain/short-term-memory)
- [LangChain 内置 middleware：摘要触发、保留边界与配置](https://docs.langchain.com/oss/python/langchain/middleware/built-in)
- 本仓库固定依赖中 `langchain==1.4.2`、`langgraph==1.2.12` 的本地源码与现有 fenced Saver。P1-B 以故障注入测试确认实际 checkpoint 顺序，不把文档示例当作已验证行为。
