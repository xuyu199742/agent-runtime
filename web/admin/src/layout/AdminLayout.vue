<script setup lang="ts">
import { computed, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import { useAuthStore } from "../stores/auth";
import { NButton, NIcon, NDropdown } from "naive-ui";
import {
  GridOutline,
  CubeOutline,
  LayersOutline,
  PeopleOutline,
  ChevronDownOutline,
  MenuOutline,
  SunnyOutline,
  MoonOutline,
  CloseOutline,
  HomeOutline,
} from "@vicons/ionicons5";
import { darkMode, toggleTheme } from "../stores/theme";

const route = useRoute();
const router = useRouter();
const auth = useAuthStore();
const collapsed = ref(false);
const mobileOpen = ref(false);
const sections = [
  {
    label: "概览",
    icon: GridOutline,
    links: [
      { label: "工作台", path: "/dashboard", permission: "dashboard:view" },
    ],
  },
  {
    label: "配置中心",
    icon: CubeOutline,
    links: [
      { label: "Agents", path: "/agents", permission: "agent:view" },
      { label: "Models", path: "/models", permission: "model:view" },
      { label: "Tools", path: "/tools", permission: "tool:view" },
    ],
  },
  {
    label: "运行中心",
    icon: LayersOutline,
    links: [
      {
        label: "Conversations",
        path: "/conversations",
        permission: "conversation:view",
      },
      { label: "Runs", path: "/runs", permission: "run:view" },
      { label: "Approvals", path: "/approvals", permission: "approval:view" },
      { label: "Artifacts", path: "/artifacts", permission: "artifact:view" },
      { label: "Workers", path: "/workers", permission: "worker:view" },
    ],
  },
  {
    label: "系统",
    icon: PeopleOutline,
    links: [
      { label: "Users", path: "/users", permission: "user:view" },
      { label: "Roles", path: "/roles", permission: "role:view" },
      { label: "Menus", path: "/menus", permission: "menu:view" },
      { label: "Permissions", path: "/permissions", permission: "role:view" },
      { label: "Audit logs", path: "/audit", permission: "audit:view" },
      { label: "System status", path: "/status", permission: "admin:access" },
    ],
  },
];
const visibleSections = computed(() =>
  sections
    .map((section) => ({
      ...section,
      links: section.links.filter((link) =>
        auth.canNavigate(link.path, link.permission),
      ),
    }))
    .filter((section) => section.links.length),
);
const title = computed(() => String(route.meta.title || "工作台"));
const initials = computed(() =>
  (auth.user?.display_name || auth.user?.username || "AR")
    .slice(0, 2)
    .toUpperCase(),
);
const userOptions = [{ label: "退出登录", key: "logout", icon: () => null }];
const openTabs = ref<{ path: string; title: string }[]>([
  { path: "/dashboard", title: "工作台" },
]);
watch(
  () => route.fullPath,
  () => {
    const path = route.path;
    if (path === "/login" || openTabs.value.some((tab) => tab.path === path))
      return;
    openTabs.value.push({ path, title: title.value });
  },
  { immediate: true },
);
function closeTab(path: string) {
  if (path === "/dashboard") return;
  const index = openTabs.value.findIndex((tab) => tab.path === path);
  if (index < 0) return;
  openTabs.value.splice(index, 1);
  if (route.path === path)
    router.push(openTabs.value[Math.max(0, index - 1)]?.path || "/dashboard");
}

async function onUserAction(key: string) {
  if (key === "logout") {
    await auth.logout();
    router.replace("/login");
  }
}
</script>

<template>
  <div class="console-shell" :class="{ collapsed }">
    <div v-if="mobileOpen" class="mobile-scrim" @click="mobileOpen = false" />
    <aside class="sidebar" :class="{ 'mobile-open': mobileOpen }">
      <div class="brand" @click="router.push('/dashboard')">
        <div class="brand-mark"><n-icon :component="CubeOutline" /></div>
        <div v-if="!collapsed" class="brand-type">
          <strong>Agent Runtime</strong><small>管理控制台</small>
        </div>
      </div>
      <nav class="nav-groups" aria-label="主导航">
        <div
          v-for="section in visibleSections"
          :key="section.label"
          class="nav-group"
        >
          <div class="nav-heading">
            <n-icon :component="section.icon" /><span v-if="!collapsed">{{
              section.label
            }}</span>
          </div>
          <router-link
            v-for="link in section.links"
            :key="link.path"
            :to="link.path"
            class="nav-link"
            :class="{
              active:
                route.path === link.path ||
                (link.path === '/runs' && route.path.startsWith('/runs/')),
            }"
            @click="mobileOpen = false"
          >
            <span v-if="!collapsed">{{ link.label }}</span
            ><span v-else class="collapsed-letter">{{ link.label[0] }}</span>
          </router-link>
        </div>
      </nav>
      <div class="sidebar-footer">
        <span class="system-pulse" /><span v-if="!collapsed"
          >Agent Runtime V0.2</span
        >
      </div>
    </aside>
    <div class="main-column">
      <header class="topbar">
        <div class="topbar-left">
          <n-button
            quaternary
            circle
            class="menu-toggle"
            aria-label="收起菜单"
            @click="collapsed = !collapsed"
            ><template #icon
              ><n-icon :component="MenuOutline" /></template></n-button
          ><n-button
            quaternary
            circle
            class="mobile-toggle"
            aria-label="打开菜单"
            @click="mobileOpen = !mobileOpen"
            ><template #icon><n-icon :component="MenuOutline" /></template
          ></n-button>
          <div class="breadcrumb">
            <n-icon :component="HomeOutline" /><span>首页</span><b>/</b
            ><strong>{{ title }}</strong>
          </div>
        </div>
        <div class="topbar-right">
          <n-button
            quaternary
            circle
            :aria-label="darkMode ? '切换浅色主题' : '切换深色主题'"
            @click="toggleTheme"
            ><template #icon
              ><n-icon
                :component="darkMode ? SunnyOutline : MoonOutline" /></template
          ></n-button>
          <div class="topbar-divider" />
          <n-dropdown :options="userOptions" @select="onUserAction"
            ><button class="user-trigger">
              <span class="avatar">{{ initials }}</span
              ><span class="user-name">{{
                auth.user?.display_name || auth.user?.username
              }}</span
              ><n-icon :component="ChevronDownOutline" /></button
          ></n-dropdown>
        </div>
      </header>
      <div class="page-tabs">
        <router-link
          v-for="tab in openTabs"
          :key="tab.path"
          :to="tab.path"
          class="page-tab"
          :class="{ active: route.path === tab.path }"
          ><span>{{ tab.title }}</span
          ><button
            v-if="tab.path !== '/dashboard'"
            class="tab-close"
            :aria-label="`关闭 ${tab.title}`"
            @click.prevent.stop="closeTab(tab.path)"
          >
            <n-icon :component="CloseOutline" /></button
        ></router-link>
      </div>
      <main class="page-body"><router-view /></main>
    </div>
  </div>
</template>
