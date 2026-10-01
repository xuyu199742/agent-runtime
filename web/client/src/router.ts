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
    { path: "/chat/:id?", component: () => import("./pages/ChatPage.vue") },
    { path: "/", redirect: "/chat" },
    { path: "/:pathMatch(.*)*", redirect: "/chat" },
  ],
});

router.beforeEach(async (to) => {
  if (to.meta.public) return true;
  const auth = useAuthStore();
  if (!auth.loggedIn) return { path: "/login", query: { next: to.fullPath } };
  try {
    await auth.load();
  } catch {
    auth.expire();
    return { path: "/login", query: { next: to.fullPath } };
  }
  return true;
});

window.addEventListener("client:auth-expired", () => {
  useAuthStore().expire();
  if (router.currentRoute.value.path !== "/login") router.replace("/login");
});

export default router;
