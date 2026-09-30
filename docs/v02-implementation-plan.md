# Agent Runtime V0.2 实施计划

基线：v0.1.0。按需求文档拆成五个顺序 PR，每个 PR 独立测试、Review、CI 和 Docker 验收后再继续。

## PR 1：API Foundation

1. 建立 /api/v1/auth、/client、/admin 三个 Transport Surface。保留 V0.1 旧接口为过渡入口，待客户端迁移完成后移除。
2. PostgreSQL 增加用户、角色、权限、菜单、登录会话与审计日志；使用强口令哈希、随机不透明 token 与服务端吊销。提供安全的首个管理员创建命令，不预置生产密码。
3. Client 请求以登录主体的 user_id 限定 Conversation、Message、Run；Admin 使用服务端 RBAC。DTO 分离，不把 prompt、model 密钥状态和 Tool policy 返回 Client。
4. 显式分页查询：Conversation、Message cursor、Run；Admin 增加配置列表、启停与归档、关联详情，以及模型最小推理连接测试。测试密钥不落库、不写日志。
5. 统一错误包含 request_id；关键 Admin 写操作写入脱敏审计日志。完成迁移、API 集成测试、权限与隔离测试、Docker E2E。

## PR 2：Runtime Execution Contract

1. Run 创建事务中生成 ExecutionSpec 与 Agent revision，Worker 在首次执行和 crash resume 时均使用冻结快照。
2. ToolExecution 进入真实 Tool 调用路径，保存 effect type、idempotency key、attempt、结果；工具失败策略显式化。
3. WAITING/Approval 与 Retry 新建 Run，记录 parent_run_id。覆盖恢复、审批和失败测试。

## PR 3：Observability

1. Redis Worker Registry TTL 心跳；PostgreSQL durable trace 仅存生命周期事件。
2. Dashboard 聚合查询与 Artifact 元数据基础。覆盖保留与权限测试。

## PR 4：Frontend Admin

基于 Vue 3、TypeScript、Vite、Naive UI、Pinia、Vue Router 实现管理后台。先连接真实 Auth/RBAC 与 API，再完成 Agent/Model/Tool、Conversation/Run、Worker/Audit 页面。路由与按钮权限只负责展示，服务端仍授权。

## PR 5：Client

实现独立聊天客户端：Agent 选择、Conversation 历史、发送/取消、SSE 重连与 step_id partial 重建；事件过期时读取 Run 最终状态。接入 Approval 和 Artifact。
