# V0.1 Review 问题记录（2026-09-29）

状态：代码修正及应用镜像构建已完成；PostgreSQL Alpine 镜像因仓库下载超时仍待数据卷兼容性验收。下表保留 review 时的原始问题和修正方向。

| 编号 | 问题 | 当前情况与位置 | 修正方向 |
| --- | --- | --- | --- |
| R-01 | 两个 PostgreSQL 地址看起来重复 | `.env.example` 的 `DATABASE_URL` 用 `postgresql+asyncpg`，供 SQLAlchemy/Alembic 使用；`CHECKPOINT_DATABASE_URL` 用 `postgresql`，供 LangGraph 的 psycopg checkpointer 使用。它们连接同一个数据库，并非两个数据库。`docker-compose.yml` 也重复配置了两项。 | 在配置说明中解释两种驱动的原因；尽量由同一个基础连接配置派生，避免主机、库名、密码修改时漂移。检查迁移和运行时是否确需分别暴露两项。 |
| R-02 | 模型配置不应放在环境变量 | `model_configs` 已保存 provider、model_name、base_url 和参数，但 `api_key_env` 只保存环境变量名，`app/runtime/factory.py` 再从进程环境读取密钥；`README.md` 和架构文档也明确要求这样做。这与用户要求不符。 | 将模型连接所需配置纳入数据库及模型管理 API；密钥采用受控的数据库存储方式，API 写入可更新、读取不回显，日志不输出。补迁移、启动/调用与安全测试。加密和密钥管理方案在实现前明确；不能把密钥原样放在普通配置 JSON 并回显。 |
| R-03 | MQ 设计未清楚呈现 | `docs/requirements.md` 第 16 节指定 Redis Streams；`docs/implementation-plan.md` Phase 3 和 `docs/architecture.md` 已描述队列，代码在 `app/infrastructure/redis_queue.py` 与 `app/worker.py`。使用 `agent:runs` Stream、`agent-workers` Consumer Group、`XADD/XREADGROUP/XACK/XAUTOCLAIM`；API 入队失败时由 Worker 扫描 PENDING Run 补投。 | 单列 MQ 设计章节，写明消息结构、投递时机、重复投递、确认/重领、租约、失败恢复和运维观察方式，并从 README 链接到该章节。 |
| R-04 | Docker 镜像应尽量小 | 应用镜像基于 `python:3.12-slim`，但 `postgres:16`、`redis:7` 使用默认标签；应用镜像 `COPY . .` 后安装依赖，可能带入不需要的构建文件。 | 将 PostgreSQL、Redis 调整为经验证兼容的轻量标签；应用镜像改用多阶段构建及精简复制范围，配合 `.dockerignore`；验证镜像大小、数据库已有数据兼容性和端到端启动。避免只凭标签名称宣称最小。 |
| R-05 | API 层从目录中看不出来 | `app/transport/` 只有 `schemas.py`；模型、工具、Agent、Session、Run、SSE 路由均写在 `app/main.py`。实施计划原列 `app/transport/http.py` 和 `sse.py`，实际没有落实。 | 按资源拆分 `app/transport/http/` 路由和 `app/transport/sse/`；`app/main.py` 仅保留应用装配、全局异常处理和健康检查。迁移路由后核对 OpenAPI 路径及响应契约。 |
| R-06 | Tool 数量增加时单文件不可维护 | `app/runtime/tools.py` 同时包含 echo、calculator、HTTP 请求与注册/构建逻辑。V0.1 仅 3 个 Tool，但后续扩展会让职责继续混杂。 | 按 Tool 实现拆为模块，保留独立 registry/factory 负责从 DB 配置组装 LangChain Tool；每个 Tool 的参数、权限、超时和测试与实现就近组织。 |
| R-07 | Review 未覆盖用户关心的架构可维护性 | 已有 `docs/verification.md` 证明自动化测试、迁移和链路检查；这些检查没有发现目录职责偏离实施计划、模型配置位置与用户预期不符、镜像选择欠精简。此前称“完成”过早。 | 增加需求逐条追踪与人工架构检查：对照原说明、实施计划和实际目录/配置；Review 结论分别报告功能验证与设计偏差，修正前不再称该版已完全符合要求。 |

## 修正顺序

先处理 R-02、R-05、R-06 的设计与接口，再处理 R-01、R-03 的配置和文档，最后调整 R-04 并重新跑迁移、自动化测试与 Docker 端到端验证。R-07 作为最终验收门槛。

## 复核结果

| 编号 | 当前结果 |
| --- | --- |
| R-01 | 只配置一个 `DATABASE_URL`，LangGraph checkpointer URL 由其转换驱动得到；单元测试覆盖密码和端口。 |
| R-02 | 模型 API Key 经 Fernet 加密后写入 `model_configs`；接口仅回显 `has_api_key`，更新可保留或轮换；主密钥由 `MODEL_SECRET_KEY` 提供。已有旧配置需要重新写入密钥。 |
| R-03 | 新增 `docs/mq-design.md`，覆盖投递、消费、ACK、重领、租约及 SSE 事件保留。 |
| R-04 | Compose 改为 PostgreSQL/Redis Alpine 标签；应用镜像改为多阶段、运行阶段不含 uv，Uvicorn 去除不用的扩展。新应用镜像构建和容器端到端运行通过；Redis Alpine 已拉取并启动检查；PostgreSQL Alpine 仍待下载及数据卷兼容性验收。 |
| R-05 | API 路由按资源放入 `app/transport/http/`，`app/main.py` 只装配全局行为和健康检查；OpenAPI 路径已核对。 |
| R-06 | `app/runtime/tools/` 中 calculator、echo、HTTP 请求各自独立，registry 只负责配置映射。 |
| R-07 | 已按原需求、实施计划、目录、API 契约、迁移和完整调用链逐项复核；测试与未完成的镜像验收分别记录在 `docs/verification.md`。 |
