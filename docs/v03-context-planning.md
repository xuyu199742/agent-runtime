# V0.3 Phase 1：Run 开始前的上下文规划

## 写入与恢复契约

创建 Run 时，Application 将 Agent Revision、分层提示词及哈希、模型配置、Tool 清单和上下文预算冻结到 ExecutionSpec schema 2。模型配置必须明确给出 `context_window` 与 `max_output_tokens`。已知 DeepSeek 模型的存量配置由迁移 `e7b4c2a91d08` 补齐；其他模型不猜测上限。管理员新增或更新模型时必须填写这两个值。

Worker 首次执行前读取当前 Session 的用户消息和最终 Assistant 消息，按冻结预算规划上下文。达到软阈值时，可把较早的完整消息批次交给同一模型生成 ConversationSummary；每次摘要请求受单独的输入预算限制。摘要调用发生在 Agent 循环外，不计入 `max_model_calls`。达到硬阈值而无法压缩时，Run 以稳定的上下文错误码结束。完整原始消息仍留在 PostgreSQL。

规划结果和新的 ConversationSummary 在持有有效租约时同事务提交。RunContextSnapshot 保存摘要引用、按顺序排列的消息 ID、预算、估算 token 数，以及覆盖摘要和消息正文的哈希。恢复时先读取快照并验证哈希，不重新选择最新 Session 历史；若已开始执行却没有快照和 checkpoint，则返回 `RUN_CONTEXT_MISSING`。LangGraph checkpoint 仍只负责该 Run 的执行状态。

ExecutionSpec schema 1 的已有 Run 继续走原来的上下文选择路径，不改写历史快照。

## 已知限制

- `approx_v1` 是保守估算，不是模型专用 tokenizer。提示词和工具 schema 的最终 token 数仍以模型服务为准。
- 这一阶段只规划 Agent 首次调用前的 Conversation Context；Run 内多轮 Tool Loop 的工作上下文压缩留待后续阶段。
- 单条历史消息连同摘要指令都放不进摘要模型输入预算时，会明确失败，不截断原文。
- ConversationSummary 只覆盖跨 Run 的用户消息和最终 Assistant 消息；Tool 消息保留在单次 Run 的 LangGraph 工作状态中。
- 摘要调用和快照提交不是同一事务；租约在摘要过程中丢失时，已发生的模型调用无法撤回，旧 Worker 不得提交规划结果。

## 验证

运行单元与集成测试：`uv run pytest -q`。隔离数据库验证迁移：先升级到 `c31a7e5b90d2`，插入已知与未知模型配置，再升级到 `e7b4c2a91d08`；降级一步不删除任何已有模型配置。Docker E2E 应使用独立数据库和 Redis DB，验证 API → Queue → Worker → 模型/Tool → 最终回答，并检查 ExecutionSpec schema 2 与 RunContextSnapshot 已落库。
