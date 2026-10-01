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

SSE 断线后使用最后收到的事件序号重连。流式文本按 `step_id` 重建，模型步骤重新执行时替换旧的未完成输出。事件过期（HTTP 410）时查询 Run 的持久状态和最终回答。浏览器刷新后会恢复本标签页正在执行的 Run；关闭标签页后可通过会话历史查看已完成的回答。
