# V0.3 Phase 3 外部写入安全实施计划

> 基于《Agent Runtime V0.3 Phase 3 — External Effect Safety》及 2026-10-16 架构评审。执行时逐项勾选；每组先写失败测试，再实现并验证。此计划覆盖 Phase 3，不包含 Capability、MCP、Skill、客户端改版或生产数据库迁移。

**目标：** 对受控外部写入建立跨 Run 稳定身份；请求结果不明时停止重发，经可信核对恢复结果或明确要求人工处理。

**架构：** PostgreSQL `EffectRecord` 保存业务效果当前事实，`ToolExecution` 保存每次模型 Tool Call 的执行事实，`RunTraceEvent` 记录 Run 内状态变化。LangGraph checkpoint 只恢复 Agent 执行。写入由固定的 Effect Contract 解析业务键和规范化请求，不开放通用 HTTP 写入配置。

**技术栈：** Python 3.12、FastAPI、SQLAlchemy 2、Alembic、PostgreSQL、LangChain/LangGraph、Redis Streams、pytest。

---

## 设计决策与边界

1. **兼容名称：** 现有 `READ_ONLY` 保持原样；新写入只用 `EXTERNAL_WRITE`。`INTERNAL_WRITE` 本阶段仅定义边界，不在 API 开放。历史数据无需重写。
2. **身份：** `EffectRecord` 唯一键为 `(provider_namespace, operation_name, business_key)`。`provider_namespace` 指实际外部账户/连接，而非 Agent 或 Run；`operation_name` 是稳定业务动作名。`request_hash` 对规范化、真正影响副作用的请求求哈希，同键异参返回 `EFFECT_IDEMPOTENCY_CONFLICT`。
3. **关系：** `tool_executions.effect_id` 可空；原有 `idempotency_key=run_id:tool_call_id` 保留为执行回放键，不当作业务键。多个 ToolExecution 可关联同一个 EffectRecord。
4. **写入路径：** 审批包装器在外层；Effect Safety 在通用 Tool 错误包装器外层。通用包装器对 `EXTERNAL_WRITE` 透传，由 Effect Safety 负责写入调用及异常分类。未知结果抛出稳定 Run 错误，不能变成普通错误 ToolMessage 让模型继续执行。
5. **发送权：** `PREPARED → DISPATCHED` 用持有有效 Run lease 的事务和 Effect 行锁完成。仅完成转换的调用者可向外发送；不在网络调用期间持有数据库锁。其他 Run 遇到已发送且未定案的 Effect，不能重新发送。
6. **核对证据：** `NOT_APPLIED` 必须证明原请求已终止且未来不会落地；仅查不到记录返回 `UNKNOWN`。原发送者仍持有有效 lease 时，其他 Run 不作失败定案。第一版不自动重发已进入 `DISPATCHED` 的 Effect。
7. **终态：** `SUCCEEDED` 可回放持久化的规范 Tool 结果；结果缺失时 fail closed。`MANUAL_REQUIRED` 阻止自动重发和 Admin Retry；本阶段不提供人工裁决 UI。Run 可用稳定错误码 `FAILED`，但 Effect 状态不能被 Run 终态覆盖。
8. **审计：** Effect 状态变更、结果和引用事件在一个数据库事务提交。跨 Run 复用记录在当前 Run 的 Timeline；Effect 当前状态从 EffectRecord 读取。后续人工裁决另设控制面流程，不在本阶段伪造终态 Run 的 Worker 事件。
9. **配置冻结：** ExecutionSpec 新 schema 版本冻结受控 Tool 的 effect 类型、operation、provider namespace 和 contract 版本；旧 schema 只允许已有只读能力，恢复时不读取最新 Tool 配置改变写入语义。
10. **承诺范围：** 相同可信业务键的写入不会由 Runtime 再次发送；模型在 Retry Run 改变业务键时，Runtime 无法推断两个键代表同一动作。受控示例须从稳定业务标识解析键，并为此加测试。

## 阶段一：持久模型与状态机（独立可验证，不开放写入）

### 任务 1：建立失败测试与迁移

**文件：** `app/persistence/database.py`；新 Alembic migration；新 `tests/integration/test_external_effects.py`。

- [ ] 先写测试：同一 `(provider_namespace, operation_name, business_key)` 并发插入只得到一条 Effect；同键异参冲突；不同外部账户允许同名业务键。
- [ ] 在隔离 `agent_test` 上执行单项测试，确认因表/列不存在而失败。
- [ ] 新建 `effect_records`：`id`、上述唯一键、`contract_version`、`request_hash`、`status`、`origin_run_id`、`dispatch_run_id`、`dispatched_at`、`external_ref`、`result_content`、`error_code`、`created_at`、`updated_at`、`resolved_at`；为 `tool_executions` 加 nullable `effect_id` 外键及索引。旧行保持 NULL。
- [ ] 增加迁移的 upgrade/downgrade 和模型一致性检查；在隔离数据库执行 `alembic upgrade head`、`alembic check`。

### 任务 2：纯状态机和持久仓库

**文件：** 新 `app/runtime/effects/contract.py`、`app/runtime/effects/state.py`、`app/persistence/repositories/effects.py`；`app/persistence/repositories/traces.py`；`tests/unit/test_effect_state.py`、`tests/integration/test_external_effects.py`。

- [ ] 先写状态表测试：`PREPARED` 可认领发送；`DISPATCHED` 不可重发；`UNCERTAIN` 只可核对；`SUCCEEDED` 只可回放；`MANUAL_REQUIRED` 禁止自动执行；非法转换抛稳定错误。
- [ ] 测试仓库事务：Effect 行变更和 `effect.*` Timeline 同时出现；租约丢失则两者均不提交；两个 Worker 竞争同一 PREPARED 时只有一个取得发送权。
- [ ] 实现有限状态转换 API，转换采用显式 `expected_status` 与 PostgreSQL 行锁/条件更新；在事务内先锁 Run，再锁 Effect，随后关联 ToolExecution。Timeline 事件只存白名单字段并引用 `effect_id`。
- [ ] 逐个运行失败测试、实现最小代码、重跑通过；运行只读 Tool 与 Timeline 回归测试。

### 任务 3：错误分类与 Retry 门禁

**文件：** `app/runtime/errors.py`、`app/worker/runner.py`、`app/persistence/repositories/runs.py`；`tests/unit/test_effect_errors.py`、`tests/integration/test_v02_retry.py`。

- [ ] 测试 `EFFECT_UNCERTAIN`、`EFFECT_MANUAL_REQUIRED`、`EFFECT_IDEMPOTENCY_CONFLICT` 原样成为 Run 错误码，不落到 `TOOL_ERROR`/`INTERNAL_ERROR`。
- [ ] 测试原 Run 有 `DISPATCHED`、`UNCERTAIN`、`RECONCILING` 或 `MANUAL_REQUIRED` Effect 时，Admin Retry 返回冲突且不创建新 Run；已定案记录按既有 Retry 流程处理。
- [ ] 实现专用异常和仓库检查；不改变只读 Tool 的 Retry 行为。

**阶段一检查点：** migration、状态机、并发认领与门禁通过；Admin Tool API 仍拒绝写入。单独提交可审阅的基础设施变更。

## 阶段二：受控外部写入、核对与恢复

### 任务 4：冻结受控 Tool Contract 与审批顺序

**文件：** `app/application/execution_spec.py`、`app/execution/config.py`、`app/runtime/agent.py`、`app/runtime/middleware.py`；`tests/unit/test_execution_schema.py`、`tests/unit/test_effect_middleware.py`。

- [ ] 测试新 ExecutionSpec 保存并恢复 `EXTERNAL_WRITE` 的 operation、provider namespace、contract version；旧 schema 和普通 Admin Tool 不能意外升级为写入。
- [ ] 测试审批拒绝时既无 EffectRecord 也无外部请求；批准和 checkpoint resume 后同一业务键只产生一个 Effect。
- [ ] 实现 `Approval → EffectSafety → ToolError → provider` 包装链；只读路径保持原样。写入的通用 `ToolErrorMiddleware` 透传原异常，EffectSafety 负责分类和持久化。

### 任务 5：受控 ticket.create 与可信核对

**文件：** 新 `app/runtime/effects/ticket.py`；`app/runtime/tools/registry.py`；测试用 Fake External Service；新 `tests/integration/test_external_effect_flow.py`。

- [ ] 从明确的稳定 `ticket_key` 生成业务键，规范化请求并计算哈希；受控 `ticket.create` 仅由代码注册且要求完整 Contract。集成测试直接种入冻结 Tool 配置，Admin Tool API 继续只接受 `READ_ONLY`，不开放任意 HTTP POST。
- [ ] Fake Service 维护已提交和在途 ledger；`create(key, payload)` 支持幂等；`reconcile(key)` 返回 `SUCCEEDED`、具有最终性证明的 `NOT_APPLIED` 或 `UNKNOWN`。普通查无记录不能返回 `NOT_APPLIED`。
- [ ] 测试正常成功、成功后响应丢失、响应返回但本地提交前崩溃、Worker 失租和旧 Worker 迟到完成。任何场景均不得创建第二张 ticket。
- [ ] 成功结果与 Effect 状态同事务落库；同 Run/跨 Run 的相同业务键回放规范 Tool 结果；缺失结果返回稳定错误码。

### 任务 6：恢复、核对与故障注入

**文件：** `app/persistence/repositories/effects.py`、`app/runtime/effects/state.py`、`app/worker/runner.py`；`tests/integration/test_external_effect_flow.py`、`tests/integration/test_worker_crash_recovery.py`。

- [ ] 故障注入：PREPARED 前后 crash、DISPATCHED 后发送前 crash、发送成功响应丢失、SUCCEEDED 提交前 crash、lease 转移、同键两个 Worker 并发、跨 Retry Run 复用、同键异参冲突。
- [ ] 核对在短事务中取得独占资格，网络调用不持锁；核对 Worker 失租后新 Worker 可接管。`UNKNOWN` 和暂时查询失败保守地保持未定案或进入 `MANUAL_REQUIRED`，不转 `FAILED`。
- [ ] 只有具有最终性证据的 `NOT_APPLIED` 可转 `FAILED`；第一版不自动重新发送。无核对能力则进入 `MANUAL_REQUIRED`。
- [ ] 核对结果写入 Effect、ToolExecution 和 Timeline 后，LangGraph 收到正确 Tool 结果；失败或不确定结果阻断模型继续调用工具。

### 任务 7：查询与回归验证

**文件：** `app/application/runs.py`、`app/transport/http/v1/admin/runs.py`、`docs/v03-external-effect-safety.md`；相关 API 测试。

- [ ] 管理端 Run 详情可通过 ToolExecution 看到关联 Effect 的当前状态、业务键的脱敏表示、外部引用及错误码；权限沿用 `run:view`，不回传任意完整业务 payload。
- [ ] 文档写清楚状态语义、业务键作用域、`NOT_APPLIED` 最终性、人工处理的当前限制、跨 Run 保证的条件、迁移与回滚。
- [ ] 在独立 `agent_test` PostgreSQL 与 Redis DB 运行新增集成测试、现有只读/审批/Timeline/恢复测试及全量 `uv run pytest -q`；运行 `uv run ruff check .`、`uv run ruff format --check .`、`alembic check`。不执行生产数据库 migration。

**阶段二完成标准：** 外部已创建 ticket、响应丢失且 Worker 崩溃/失租后，新 Worker 不再发送创建请求，核对找回第一次结果，Agent 获得可回放的 Tool 结果；同键跨 Retry Run 仍不重复创建。上述流程在隔离 E2E 中可复现。

## 基线与资料

- 基线提交：`origin/master` 的 `936aef0`；当前工作区为独立分支 `codex/v03-external-effect-safety`。
- 2026-10-16 隔离基线：首次全量测试 103 通过、1 个检查点清理用例失败；该用例单独重跑通过，随后全量复跑 `104 passed`。后续若该用例再波动，先排查测试数据/清理竞态，不混入 Effect 改动。
- PostgreSQL 并发去重采用 SQLAlchemy PostgreSQL `INSERT ... ON CONFLICT` 与唯一约束；参见官方文档：https://docs.sqlalchemy.org/en/20/dialects/postgresql.html#insert-on-conflict-upsert 。
