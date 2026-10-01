import { defineStore } from "pinia";
import { computed, ref } from "vue";
import { api } from "../api/client";

export interface Principal {
  id: string;
  username: string;
  display_name: string;
  roles: string[];
  permissions: string[];
}
interface Tokens {
  access_token: string;
  refresh_token: string;
}

export const useAuthStore = defineStore("auth", () => {
  const user = ref<Principal | null>(null);
  const menus = ref<{ path: string }[]>([]);
  const loading = ref(false);
  const accessToken = ref(sessionStorage.getItem("admin_access_token"));
  const isLoggedIn = computed(() => !!accessToken.value);
  const can = (permission: string) =>
    !!user.value &&
    (user.value.permissions.includes("*") ||
      user.value.permissions.includes(permission));
  const canNavigate = (path: string, permission: string) =>
    can(permission) &&
    (menus.value.length === 0 ||
      menus.value.some((menu) => menu.path === path));

  async function loadMenus() {
    if (can("admin:access")) {
      try {
        menus.value = await api.get<{ path: string }[]>(
          "/api/v1/admin/me/menus",
        );
      } catch {
        menus.value = [];
      }
    }
  }

  async function load(): Promise<void> {
    if (!isLoggedIn.value || user.value) return;
    loading.value = true;
    try {
      user.value = await api.get<Principal>("/api/v1/auth/me");
      await loadMenus();
    } finally {
      loading.value = false;
    }
  }

  async function login(username: string, password: string): Promise<void> {
    const tokens = await api.post<Tokens>("/api/v1/auth/login", {
      username,
      password,
    });
    sessionStorage.setItem("admin_access_token", tokens.access_token);
    sessionStorage.setItem("admin_refresh_token", tokens.refresh_token);
    accessToken.value = tokens.access_token;
    user.value = await api.get<Principal>("/api/v1/auth/me");
    await loadMenus();
  }

  async function logout(): Promise<void> {
    try {
      await api.post<void>("/api/v1/auth/logout");
    } catch {
      /* 本地凭证仍需清理 */
    }
    sessionStorage.removeItem("admin_access_token");
    sessionStorage.removeItem("admin_refresh_token");
    accessToken.value = null;
    user.value = null;
    menus.value = [];
  }

  return {
    user,
    menus,
    loading,
    isLoggedIn,
    can,
    canNavigate,
    load,
    login,
    logout,
  };
});
