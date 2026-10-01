<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { NButton, NForm, NFormItem, NInput, useMessage } from "naive-ui";
import { useAuthStore } from "../stores/auth";

const route = useRoute(),
  router = useRouter(),
  auth = useAuthStore(),
  message = useMessage();
const username = ref(""),
  password = ref(""),
  loading = ref(false);
async function submit() {
  if (!username.value || !password.value) {
    message.warning("请输入用户名和密码");
    return;
  }
  loading.value = true;
  try {
    await auth.login(username.value.trim(), password.value);
    if (!auth.can("admin:access")) {
      await auth.logout();
      message.error("当前账号没有管理后台权限");
      return;
    }
    router.replace(
      typeof route.query.next === "string" ? route.query.next : "/dashboard",
    );
  } catch (error) {
    message.error(error instanceof Error ? error.message : "登录失败");
  } finally {
    loading.value = false;
  }
}
</script>

<template>
  <div class="login-page">
    <section class="login-art">
      <div class="login-grid" />
      <div class="login-art-content">
        <div class="login-brand">
          <span class="login-logo">✳</span> AGENT<span>RUNTIME</span>
        </div>
        <div class="login-eyebrow">SYSTEM / CONTROL PLANE</div>
        <h1>掌控每一次<br /><em>智能执行。</em></h1>
        <p>
          统一管理 Agent 配置、运行轨迹和人工审批。<br />让运行状态清晰可见，让决策始终可控。
        </p>
        <div class="login-art-foot">
          <span class="live-dot" /> OPERATIONS ONLINE <span>V0.2</span>
        </div>
      </div>
    </section>
    <section class="login-form-side">
      <div class="login-form-wrap">
        <div class="login-index">01 / ACCESS</div>
        <h2>欢迎回来</h2>
        <p class="login-subtitle">登录 Agent Runtime 管理控制台</p>
        <n-form @submit.prevent="submit"
          ><n-form-item label="用户名"
            ><n-input
              v-model:value="username"
              size="large"
              placeholder="输入用户名"
              autocomplete="username" /></n-form-item
          ><n-form-item label="密码"
            ><n-input
              v-model:value="password"
              size="large"
              type="password"
              show-password-on="click"
              placeholder="输入密码"
              autocomplete="current-password"
              @keyup.enter="submit" /></n-form-item
          ><n-button
            type="primary"
            size="large"
            block
            :loading="loading"
            attr-type="submit"
            class="login-submit"
            >进入控制台 <span>→</span></n-button
          ></n-form
        >
        <div v-if="route.query.forbidden" class="login-warning">
          当前账号没有管理后台权限。
        </div>
        <div class="login-form-foot">
          AUTHORIZED PERSONNEL ONLY · SECURE ACCESS
        </div>
      </div>
    </section>
  </div>
</template>
