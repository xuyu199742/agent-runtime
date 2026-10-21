# Agent Runtime 客户端

面向普通用户的 Vue 3 对话界面，使用 V0.2 `/api/v1/auth` 和 `/api/v1/client` 接口。提供登录、Agent 选择、会话管理、流式回答、停止、审批以及会话文件预览和下载。

## 本地运行

先启动仓库根目录的 PostgreSQL、Redis、API 和 Worker，再在本目录运行：

```bash
npm ci
npm run dev
```

打开 `http://localhost:5174`。Vite 将 `/api` 请求转发到 `http://localhost:8000`。生产部署时应由同源反向代理将 `/api` 转发到 API 服务；前端不包含模型凭证。

```bash
npm run format:check
npm test
npm run build
```

默认使用 AG-UI 事件流，断线后携带最后收到的事件游标重连。模型正文与真实推理、工具调用输入输出及错误、实际 Skill 读取信息按累计快照替换，不重复追加。没有返回推理时不会生成模拟思考；配置的 Skill 只有实际读取后才出现在过程记录中。

刷新或切换会话时，按消息的 `run_id` 从 `/runs/{id}/activity` 恢复过程记录，进行中的 Run 会继续订阅。历史回答前可展开执行过程、思考、工具与 Skill。失败或停止且没有最终回答的 Run 仍保留执行记录和已生成文本。文件通过右侧面板阅读、查看源文或下载，小屏幕使用覆盖面板。

显式设置 `VITE_AGUI_ENABLED=false` 可切换到旧 SSE 流，该兼容模式不提供完整的实时活动。详情见 [AG-UI 适配说明](../../docs/ag-ui-adapter.md)。
