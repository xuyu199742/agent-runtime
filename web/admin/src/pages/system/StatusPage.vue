<script setup lang="ts">
import { onMounted, ref } from "vue";
import { NButton, NIcon, useMessage } from "naive-ui";
import { RefreshOutline } from "@vicons/ionicons5";
import PageHeader from "../../components/PageHeader.vue";
import { api } from "../../api/client";

const health = ref("未知"),
  ready = ref("未知"),
  loading = ref(false),
  message = useMessage();
async function load() {
  loading.value = true;
  try {
    health.value = (await api.get<{ status: string }>("/health")).status;
    ready.value = (await api.get<{ status: string }>("/ready")).status;
  } catch (error) {
    ready.value = "不可用";
    message.error(error instanceof Error ? error.message : "状态检查失败");
  } finally {
    loading.value = false;
  }
}
onMounted(load);
</script>
<template>
  <page-header
    eyebrow="SYSTEM / HEALTH"
    title="系统状态"
    description="检查 API 与依赖服务的就绪状态。"
    ><n-button secondary :loading="loading" @click="load"
      ><template #icon><n-icon :component="RefreshOutline" /></template
      >重新检查</n-button
    ></page-header
  >
  <div class="status-grid">
    <div class="panel status-panel">
      <div class="page-eyebrow">01 / API</div>
      <h3>HTTP 服务</h3>
      <strong
        ><span
          class="status-dot"
          :class="health === 'ok' ? 'success' : 'error'"
        />{{ health }}</strong
      >
      <p>健康探针返回的服务状态。</p>
    </div>
    <div class="panel status-panel">
      <div class="page-eyebrow">02 / DEPENDENCIES</div>
      <h3>PostgreSQL + Redis</h3>
      <strong
        ><span
          class="status-dot"
          :class="ready === 'ready' ? 'success' : 'error'"
        />{{ ready }}</strong
      >
      <p>就绪探针确认数据库与消息服务可连接。</p>
    </div>
  </div>
</template>
<style scoped>
.status-grid {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 16px;
}
.status-panel {
  padding: 27px;
}
.status-panel h3 {
  font-size: 15px;
  margin: 18px 0;
}
.status-panel strong {
  font-family: "IBM Plex Mono", monospace;
  font-size: 24px;
}
.status-panel p {
  font-size: 11px;
  color: var(--muted);
  margin: 20px 0 0;
}
@media (max-width: 700px) {
  .status-grid {
    grid-template-columns: 1fr;
  }
}
</style>
