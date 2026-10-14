# V0.3 Phase 2 可靠性边界

本阶段沿用 Run、ModelExecution、ToolExecution、Approval、RunTraceEvent 与 LangGraph PostgreSQL Checkpointer；没有新增业务表或数据库迁移。`thread_id` 仍是 `run_id`。

## 恢复矩阵

| 故障点 | PostgreSQL 事实 | LangGraph 检查点 | 恢复动作 | 自动重试是否安全 |
| --- | --- | --- | --- | --- |
| 模型请求前 | 无新模型事实 | 上一个检查点 | 恢复执行 | 是 |
| 模型响应已记录、检查点未写 | ModelExecution=COMPLETED | 上一个检查点 | 同一步重新调用模型，新增 attempt，保留旧响应 | 可重调模型；旧响应不代表决策已应用 |
| Tool 请求前 | ToolExecution=STARTED | 当前或上一个检查点 | 只读 Tool 可重试 | 仅限当前只读 Tool |
| Tool 成功且结果可重放 | ToolExecution=COMPLETED、结果非 NULL | 可能落后 | 重放已存结果，禁止再次调用 Tool | 是，按同一 Run/Tool Call ID 重放 |
| Tool 已完成但结果缺失 | ToolExecution=COMPLETED、结果为 NULL | 可能落后 | `TOOL_RESULT_UNAVAILABLE`，Run 失败并保留事实 | 否；需核对原操作 |
| 外部请求已成功、写 ToolExecution 前崩溃 | 仍可能是 STARTED | 可能落后 | 当前代码不能判定外部效果；未来外部写入工具必须先有幂等与核对协议 | 否；当前没有外部写入 Tool |
| 等待审批、检查点缺失 | Approval 已存在/已决策 | 无 | `APPROVAL_RECOVERY_LOST`，Run 失败，不重新运行模型或 Tool | 否；需人工核对 |
| 检查点数据库临时不可用 | 业务事实保留 | 暂时不可读 | 停止当前执行，保留队列待租约恢复；不能误判为检查点丢失 | 待服务恢复 |
| 旧 Worker 丢失租约后写入 | 业务事实被租约围栏拒绝 | 官方 Saver 自身不围栏 | 写入事务锁定 Run 并验证租约；旧 Worker 写入被拒绝 | 新 Worker 可从最新有效检查点恢复 |
| Redis 发布失败 | 已提交事实和 Timeline 保留 | 不受影响 | 记录告警，客户端通过 API/SSE 重连读取当前 Run | 不回滚 PostgreSQL |

`ModelExecution.COMPLETED` 的语义是“模型响应已被观察并持久化”。它不声称 LangGraph 已经应用该决策。两套 PostgreSQL 连接没有共同事务，所以崩溃后同一步可能有多次模型调用；`(run_id, step_id, attempt)` 保留每次结果，Timeline 逐次记录。本阶段没有可靠且低侵入的“决策已应用”业务事实，不额外制造一个可能误导人的状态。

## 检查点围栏

官方 `AsyncPostgresSaver` 单独使用时，只按 `thread_id` 保存检查点，不检查 Run 租约。竞态测试让旧 Worker 在租约转移后迟到写入，证明它仍能成为最新检查点。

Worker 执行 Run 时使用 `LeaseFencedPostgresSaver`。其 `aput` 和 `aput_writes` 在**同一个 psycopg 事务**内先 `SELECT runs ... FOR UPDATE`，验证 `RUNNING`、`lease_owner`、未过期租约，再调用官方 Saver 写入。租约转移与检查点写入通过 Run 行锁串行化。普通检查点读取和终态清理继续使用官方 Saver。租约检查失败时取消旧执行，不写检查点。这个薄层不改变 LangGraph 的图循环或检查点结构。

## 审批与时间线

执行事件继续用 Worker 租约分配 `Run.trace_sequence`。审批批准、拒绝和取消是控制面事件：先锁 Run，再锁 Approval，在审批状态事务里追加 `approval.approved`、`approval.rejected` 或 `approval.cancelled`。审批事件引用 Approval ID；决策人只在管理端审批详情与持久事件数据中可见，客户端审批 API 不暴露该字段。

管理后台从 `/timeline` 读取持久顺序与 attempt。客户端失败后清除过期审批卡片和部分模型输出。失败不等于可安全重复；重新发起新 Run 前应核对原 Run 的 Tool 和 Timeline。当前同一 Tool Call 的幂等键作用域为 Run，**不保证跨 Retry Run 去重**。
