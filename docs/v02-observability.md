# V0.2 可观测性与 Artifact 基础

## Worker 实时状态

Worker 每 5 秒向 Redis 写入 `worker:{worker_id}`，TTL 为 15 秒。记录容量、当前执行数、启动和心跳时间。正常退出会删除记录；进程异常退出后由 TTL 清理。Admin Worker 列表以 Redis 为准，详情中的 Run 列表来自 PostgreSQL，瞬时变化可能存在短暂差异。

## Run Trace

Redis Run Event 用于实时 SSE 和短期重放；PostgreSQL `run_trace_events` 保存长期生命周期记录。Trace 只接受固定事件类型和字段白名单，不存 `model.delta`、消息正文、模型最终回答或 Tool 参数。Run 的终态 Trace 与状态更新在同一数据库事务中提交。历史 Trace 按事件 ID 升序分页。

Trace 不替代业务审计日志，也不保证外部操作和数据库之间的原子性。Worker 在持久化非终态 Trace 后发布 Redis 事件；若 Redis 暂时不可用，数据库记录仍保留。

## Dashboard 口径

`today_runs`、`failed`、平均耗时和成功率按 UTC 当天创建的 Run 统计；`running`、`waiting` 为当前全量状态。趋势及模型使用量查询最近七个 UTC 自然日；队列深度来自 Redis Stream，Worker 容量来自在线注册表。若 Redis 不可用，接口返回服务不可用，不伪造零容量。

## Artifact

PostgreSQL 保存元数据，文件存放在本地目录 `ARTIFACT_STORAGE_DIR`，Docker API 与 Worker 共享 `artifact_data` volume。文件名会去除路径部分；存储 key 为随机值，并验证读取路径不越界。单个文件上限 50 MB。Client 只能列出和下载自己 Conversation 下的 Artifact；Admin 需要 `artifact:view` 权限。API 不返回内部 `storage_key`。

当前提供 Artifact 存储和查询基础，没有自动产出 Artifact 的 Tool。未来新增生成者时，应先校验可发布的 metadata，避免将密钥等敏感数据放入 Client 可见字段。本地目录适合单机或共享卷部署；多节点无共享文件系统时需接入对象存储。
