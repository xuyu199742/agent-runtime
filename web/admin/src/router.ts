import { createRouter, createWebHistory } from "vue-router";
import { useAuthStore } from "./stores/auth";

const router = createRouter({
  history: createWebHistory(),
  routes: [
    {
      path: "/login",
      component: () => import("./pages/LoginPage.vue"),
      meta: { public: true },
    },
    {
      path: "/",
      component: () => import("./layout/AdminLayout.vue"),
      children: [
        { path: "", redirect: "/dashboard" },
        {
          path: "dashboard",
          component: () => import("./pages/DashboardPage.vue"),
          meta: { title: "工作台", permission: "dashboard:view" },
        },
        {
          path: "agents",
          component: () => import("./pages/catalog/AgentsPage.vue"),
          meta: { title: "Agent 管理", permission: "agent:view" },
        },
        {
          path: "models",
          component: () => import("./pages/catalog/ModelsPage.vue"),
          meta: { title: "模型配置", permission: "model:view" },
        },
        {
          path: "tools",
          component: () => import("./pages/catalog/ToolsPage.vue"),
          meta: { title: "工具注册", permission: "tool:view" },
        },
        {
          path: "conversations",
          component: () => import("./pages/runtime/ConversationsPage.vue"),
          meta: { title: "会话", permission: "conversation:view" },
        },
        {
          path: "runs",
          component: () => import("./pages/runtime/RunsPage.vue"),
          meta: { title: "Runs", permission: "run:view" },
        },
        {
          path: "runs/:id",
          component: () => import("./pages/runtime/RunDetailPage.vue"),
          meta: { title: "Run 详情", permission: "run:view" },
        },
        {
          path: "approvals",
          component: () => import("./pages/runtime/ApprovalsPage.vue"),
          meta: { title: "审批", permission: "approval:view" },
        },
        {
          path: "artifacts",
          component: () => import("./pages/runtime/ArtifactsPage.vue"),
          meta: { title: "文件产物", permission: "artifact:view" },
        },
        {
          path: "workers",
          component: () => import("./pages/runtime/WorkersPage.vue"),
          meta: { title: "Workers", permission: "worker:view" },
        },
        {
          path: "users",
          component: () => import("./pages/system/UsersPage.vue"),
          meta: { title: "用户", permission: "user:view" },
        },
        {
          path: "roles",
          component: () => import("./pages/system/RolesPage.vue"),
          meta: { title: "角色", permission: "role:view" },
        },
        {
          path: "menus",
          component: () => import("./pages/system/MenusPage.vue"),
          meta: { title: "菜单", permission: "menu:view" },
        },
        {
          path: "permissions",
          component: () => import("./pages/system/PermissionsPage.vue"),
          meta: { title: "权限", permission: "role:view" },
        },
        {
          path: "audit",
          component: () => import("./pages/system/AuditPage.vue"),
          meta: { title: "审计日志", permission: "audit:view" },
        },
        {
          path: "status",
          component: () => import("./pages/system/StatusPage.vue"),
          meta: { title: "系统状态", permission: "admin:access" },
        },
      ],
    },
    { path: "/:pathMatch(.*)*", redirect: "/dashboard" },
  ],
});

router.beforeEach(async (to) => {
  if (to.meta.public) return true;
  const auth = useAuthStore();
  if (!auth.isLoggedIn) return { path: "/login", query: { next: to.fullPath } };
  try {
    await auth.load();
  } catch {
    return { path: "/login", query: { next: to.fullPath } };
  }
  if (!auth.can("admin:access"))
    return { path: "/login", query: { forbidden: "1" } };
  if (to.meta.permission && !auth.can(String(to.meta.permission)))
    return { path: "/dashboard" };
  return true;
});

export default router;
