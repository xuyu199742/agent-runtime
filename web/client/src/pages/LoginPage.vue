<script setup lang="ts">
import { ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { NButton, NInput, useMessage } from "naive-ui";
import { ArrowForwardOutline, SparklesOutline } from "@vicons/ionicons5";
import { useAuthStore } from "../stores/auth";

const username = ref(""),
  password = ref(""),
  busy = ref(false);
const auth = useAuthStore(),
  router = useRouter(),
  route = useRoute(),
  message = useMessage();
async function submit() {
  if (!username.value.trim() || !password.value) {
    message.warning("请输入用户名和密码");
    return;
  }
  busy.value = true;
  try {
    await auth.login(username.value.trim(), password.value);
    await router.replace(
      typeof route.query.next === "string" ? route.query.next : "/chat",
    );
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "登录失败");
  } finally {
    busy.value = false;
  }
}
</script>
<template>
  <div class="login-screen">
    <div class="login-side">
      <div class="login-brand">
        <div class="brand-symbol"><n-icon :component="SparklesOutline" /></div>
        <span>Agent Runtime</span>
      </div>
      <div class="login-intro">
        <span class="eyebrow">YOUR THINKING SPACE</span>
        <h1>让想法，<br /><em>继续生长。</em></h1>
        <p>与 Agent 自然对话。每一次提问、执行和结果，都清晰地留在这里。</p>
      </div>
      <div class="login-foot">
        一个安静、可靠的智能工作空间 <span>V0.2</span>
      </div>
    </div>
    <div class="login-form-side">
      <div class="login-form">
        <div class="login-overline">欢迎回来</div>
        <h2>开始对话</h2>
        <p>登录后继续你的工作空间</p>
        <form @submit.prevent="submit">
          <label for="username">用户名</label
          ><n-input
            id="username"
            v-model:value="username"
            size="large"
            placeholder="请输入用户名"
            :input-props="{ autocomplete: 'username' }"
          /><label for="password">密码</label
          ><n-input
            id="password"
            v-model:value="password"
            size="large"
            type="password"
            show-password-on="click"
            placeholder="请输入密码"
            :input-props="{ autocomplete: 'current-password' }"
          /><n-button
            type="primary"
            block
            size="large"
            attr-type="submit"
            :loading="busy"
            >进入工作空间 <n-icon :component="ArrowForwardOutline"
          /></n-button>
        </form>
      </div>
    </div>
  </div>
</template>
