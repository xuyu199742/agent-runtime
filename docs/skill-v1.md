# Skill V1：版本化 Context Source

Skill 由管理员通过 `/api/v1/admin/skills` 创建，正文是 `SKILL.md` 内容，资源只能位于 `references/`。发布新版本使用 `POST /api/v1/admin/skills/{id}/revisions`；版本只能追加，不允许修改旧版。管理接口沿用 `agent:view`、`agent:update` 权限并记录审计。

Agent 的 `skill_ids` 决定新 Run 可用的 Skill。创建 Run 时，ExecutionSpec v6 冻结每个 Skill 的版本号、正文、资源、内容哈希与目录元数据。Run 恢复只读取该快照，即使管理员发布新版本或禁用 Skill，也不会切换旧 Run 内容。无 Skill 的新 Run 仍为 v5；旧 v1–v5 的恢复路径不变。

模型最初只看到 Skill 目录的名称、说明和适用场景。需要正文或 `references/` 资源时调用只读的 `skill.read` Tool；ToolExecution 与 Timeline 继续走现有 Policy、Budget 和记录路径，返回内容进入 Working Context 预算。Skill 内容是低信任数据，不具备授予工具权限的能力；`scripts/` 不可读取或执行。正文和每个资源限制 32 KiB，最多 32 个资源；资源路径禁止绝对路径、反斜杠、路径穿越和非 `references/` 前缀。不允许网络资源。

迁移 `a14c9d3f5602` 增加 `skills`、`skill_revisions`、`agent_skills`。升级不修改现有 Agent 或 Run；降级会删除 Skill 目录和历史版本，执行前应导出相关数据。旧 ExecutionSpec 不需回填。
