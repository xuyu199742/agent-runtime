import { defineStore } from "pinia";
import { ref } from "vue";
import { api, clearSession, hasSession, saveSession } from "../api/http";
import type { User } from "../types/api";

export const useAuthStore = defineStore("client-auth", () => {
  const user = ref<User | null>(null);
  const loggedIn = ref(hasSession());

  async function load(): Promise<void> {
    if (user.value || !loggedIn.value) return;
    user.value = await api.get<User>("/api/v1/auth/me");
  }

  async function login(username: string, password: string): Promise<void> {
    const tokens = await api.post<{
      access_token: string;
      refresh_token: string;
    }>("/api/v1/auth/login", { username, password });
    saveSession(tokens);
    loggedIn.value = true;
    user.value = await api.get<User>("/api/v1/auth/me");
  }

  async function logout(): Promise<void> {
    try {
      await api.post<void>("/api/v1/auth/logout");
    } catch {
      /* 本地会话仍需清除 */
    }
    clearSession();
    user.value = null;
    loggedIn.value = false;
  }

  function expire(): void {
    clearSession();
    user.value = null;
    loggedIn.value = false;
  }

  return { user, loggedIn, load, login, logout, expire };
});
