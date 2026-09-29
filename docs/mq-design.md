# MQ 设计：Redis Streams

V0.1 使用 Redis Streams 作为 Run 队列，不引入 RabbitMQ 或 Celery。PostgreSQL 的 `runs` 表是运行状态的权威数据源；队列项只是唤醒 Worker 的信号。

## 投递与恢复

API 在同一数据库事务中创建 Message 与 `PENDING` Run，提交后向 `agent:runs` Stream `XADD` 一条 `run_id`。Redis 投递失败时，Run 仍留在数据库；Worker 定期扫描 `PENDING` Run 补投。Redis 中短期键抑制重复补投，数据库抢占状态负责最终去重，因此不依赖 Redis 键提供严格恰好一次语义。

## 消费与确认

Worker 加入 `agent-workers` Consumer Group，通过 `XREADGROUP` 读取队列项。领取前用数据库条件更新将 Run 从 `PENDING` 改为 `RUNNING` 并记录租约和 Worker 标识；未取得租约的 Worker 不执行。执行期间刷新租约；完成后持有租约的 Worker 写入终态和回答，再用 `XACK` 确认并删除队列项。

Worker 崩溃或确认失败时，其他 Worker 用 `XAUTOCLAIM` 认领空闲队列项。数据库租约过期后可重新抢占，LangGraph checkpoint 用于继续执行。重复队列项不应产生第二个活跃执行者；外部有副作用 Tool 的幂等性仍需单独设计。

## 事件流

每个 Run 的模型和 Tool 事件写入独立 Redis Stream，SSE 使用事件序号回放并跟随新事件。终态流保留 24 小时，超期客户端读取 PostgreSQL 中持久的 Run 状态与最终回答。SSE 连接断开不影响 Worker 或队列消息。
