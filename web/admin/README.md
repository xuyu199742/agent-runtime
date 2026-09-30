# Agent Runtime 管理后台

基于 Vue 3、TypeScript、Vite、Naive UI、Pinia 与 Vue Router。布局和交互参考 [Naive UI Admin](https://github.com/jekip/naive-ui-admin)，业务页面针对 Agent Runtime API 实现。

## 本地运行

后端需在 `127.0.0.1:8000` 运行。前端开发服务通过 Vite 代理 `/api`、`/health`、`/ready`。

```bash
cd web/admin
npm ci
npm run dev
```

打开 `http://localhost:5173`。生产构建执行 `npm run build`，静态文件输出到 `dist/`。

模型连接测试会调用真实模型服务。若服务仅在内网可用，运行后端的主机也必须能访问对应的 Base URL。
