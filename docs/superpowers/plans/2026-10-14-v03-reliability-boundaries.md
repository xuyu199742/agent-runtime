# V0.3 Phase 2 实施计划

## 范围与判断

本次只收紧现有 Run、ToolExecution、Approval、Timeline 和 LangGraph 恢复边界，并同步调整管理后台与客户端。沿用现有数据库表；暂不新增迁移。

## 执行顺序

1. 为 `COMPLETED + result_content=NULL`、审批恢复时检查点缺失、模型事实先于检查点、旧 Worker 迟到写入、审批决策时间线编写可复现测试。
2. Tool 已完成且结果不可重建时抛稳定错误，禁止再次调用 Tool；错误不能被普通 Tool 失败策略吞掉。
3. Runtime 提供检查点/interrupt 查询方法，Worker 只接收 Runtime DTO。对已进入审批边界但缺少检查点的 Run 以 `APPROVAL_RECOVERY_LOST` 失败；检查点数据库暂时不可用则保留待恢复的 Run。
4. Approval 决策与取消使用 Run 行锁分配统一 sequence，并在同一事务写入 timeline。固定加锁顺序为 Run → Approval。
5. 注入模型事实与检查点之间的故障，验证同一步的 attempt 递增、旧事实保留；注入租约转移竞态，判断旧 Worker 是否仍可落检查点，再选择最小围栏措施。
6. 管理后台 Run 详情读取现有 `/timeline`，显示 sequence、attempt、引用和恢复错误；审批详情显示决策人/时间。客户端在终态刷新审批列表并显示可读恢复错误。
7. 补 `docs/v03-reliability-boundaries.md` 恢复矩阵；运行后端全套测试、前端测试/构建、隔离数据库 E2E，复审差异，提交一个 PR 后停止。

## 关键边界

- `ModelExecution.COMPLETED` 表示观察到模型响应，不保证 LangGraph 已持久化该决策。
- Redis 失败不回滚已提交的 PostgreSQL 事实；LangGraph saver 与业务事务不能合并。
- 当前 Tool 仅有只读实现；未来外部写入成功但响应丢失的情况需要独立的 effect/reconcile 设计。本次不声称失败 Run 可以安全重试。
