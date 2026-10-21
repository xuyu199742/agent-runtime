# 对话执行过程与 DeerFlow 风格界面实施计划

## 已确认目标
用户确认交互原型，并要求工具调用、实际 Skill 读取、模型实际返回的推理内容全部支持。保持 Vue 3 客户端与现有 Runtime 架构；不以假步骤冒充推理，不将目录中的 Skill 误记成已加载。

## 数据契约
- 用户可见、归属于 Run 的 Activity：`{id,type,content}`。
- model：stepId、status、累计 text、累计 reasoning。
- tool：name、status、toolCallId、脱敏且有界的 input/output/error。
- skill：name、status、toolCallId、resource、冻结 revision/contentHash；成功读取才记为已加载。
- GET `/api/v1/client/runs/{id}/activity` 返回 `{items: Activity[]}`；使用已有 Run 所有权校验。
- AG-UI ACTIVITY_SNAPSHOT 使用相同完整快照，客户端按 id 替换，支持幂等重放。
- 消息接口增加可选 run_id，供历史消息查询活动。
- PostgreSQL 保存恢复事实；RunTraceEvent 只存索引，流式正文与推理另存，写入沿用 worker lease fence。

## 任务
1. 后端活动持久化、流式聚合、工具/Skill 明细和历史查询。重点验证重试、失败、租约失效、跨用户授权、AG-UI 游标与刷新重放。
2. 模型兼容适配：捕获 OpenAI-compatible `reasoning_content`，保留工具续调用所需字段；标准 OpenAI 接口不发送第三方参数。模型管理增加明确的推理选项，并保留既有配置。
3. 客户端按已确认 HTML 原型重构布局，保留停止、审批、历史、报告预览。展示真实活动和可折叠模型推理；无返回时隐藏推理；历史活动按 Run 恢复。
4. 独立 Review，运行 Python 单元/集成、前端测试和构建；实际模型验证推理与工具续调用；更新本地运行服务并浏览器验收。

## 代码边界
- 后端：app/runtime/agent.py、app/worker、app/persistence、app/transport/agui.py、client routes/schemas、迁移和对应测试。
- 模型：app/runtime/factory.py、兼容适配模块、app/transport/schemas/legacy.py、web/admin/src/pages/catalog/ModelsPage.vue。
- 前端：web/client/src 下组件、useChat、stream、types、style 和测试。

## 验证隔离
集成测试只用 PostgreSQL `agent_test` (localhost:5434)、Redis db1 (localhost:6380)，不得清理用户使用的 `agent`。实际模型探针只输出结果类型、长度和成功状态，不打印凭证。新功能基于 PR19 修复分支，作为后续独立提交评审。

## 实施与验收记录
- 已落地独立持久快照、AG-UI 累计重放、旧工具事实 fallback、历史 run_id 与会话所有权隔离。
- 已落地 DeepSeek 真实推理字段接收/工具续调；旧缺字段检查点明确报 REASONING_CONTEXT_MISSING，未伪造推理。
- 真实联调发现 skill.read 不符合供应商工具名规则，现于 wire 边界确定性转换并还原；Chat Completions 真实验证，Responses 共同返回边界使用离线测试覆盖，未声称真实 Responses 服务验收。
- 前端沿用 Vue，实现暖色对话布局、折叠活动、失败/取消部分正文、实际 Skill 版本/资源/哈希、报告预览与刷新恢复。
- Python 全量 271 passed，客户端 14 passed，客户端和管理端构建通过；后续工具适配共同返回边界专项复验通过。
- 真实 DeepSeek 验收 Run 0a301d0b-c62e-4e7c-9708-b3c426ce57ab：COMPLETED，3 模型步骤、3 工具调用、2 次实际 Skill 读取；真实返回26字符推理，结果437。浏览器展开与刷新恢复通过，无页面异常。
- 本地服务已应用 b7605ee41d20；迁移前备份在 Downloads/agent-server-before-activity-2026-10-21.dump。演示助手与原默认助手配置分开。
- 展示正文与推理各64KiB、工具预览8KiB，截断明确标记；凭证预览为保守过滤，不保证从任意自由文本识别所有秘密，认证 headers 整体隐藏。
