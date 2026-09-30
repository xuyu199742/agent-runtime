<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { NButton, NIcon, NProgress, NSpin, useMessage } from "naive-ui";
import { RefreshOutline } from "@vicons/ionicons5";
import { useRouter } from "vue-router";
import PageHeader from "../../components/PageHeader.vue";
import { api } from "../../api/client";

interface Worker {
  worker_id: string;
  hostname: string;
  runtime_version: string;
  capacity: number;
  running: number;
  started_at: string;
  heartbeat_at: string;
  current_runs?: string[];
}
const workers = ref<Worker[]>([]),
  loading = ref(false),
  selected = ref<Worker | null>(null),
  message = useMessage(),
  router = useRouter();
const totalCapacity = computed(() =>
  workers.value.reduce((sum, worker) => sum + worker.capacity, 0),
);
const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { hour12: false });
let timer: ReturnType<typeof setInterval> | undefined;
async function load() {
  loading.value = true;
  try {
    workers.value = await api.get<Worker[]>("/api/v1/admin/workers");
    if (selected.value)
      selected.value =
        workers.value.find(
          (worker) => worker.worker_id === selected.value?.worker_id,
        ) || null;
  } catch (error) {
    message.error(error instanceof Error ? error.message : "Worker 加载失败");
  } finally {
    loading.value = false;
  }
}
async function select(worker: Worker) {
  try {
    selected.value = await api.get<Worker>(
      `/api/v1/admin/workers/${encodeURIComponent(worker.worker_id)}`,
    );
  } catch (error) {
    message.error(error instanceof Error ? error.message : "Worker 详情失败");
  }
}
onMounted(() => {
  load();
  timer = setInterval(load, 15000);
});
onUnmounted(() => {
  if (timer) clearInterval(timer);
});
</script>
<template>
  <page-header
    eyebrow="RUNTIME / WORKERS"
    title="Workers"
    description="在线状态由 Redis TTL 心跳决定，离线 Worker 会自动移出列表。"
    ><n-button secondary :loading="loading" @click="load"
      ><template #icon><n-icon :component="RefreshOutline" /></template
      >刷新</n-button
    ></page-header
  >
  <div class="worker-summary panel">
    <span class="status-dot success" /><strong>{{ workers.length }} 在线</strong
    ><span>{{ totalCapacity }} 总并发容量</span
    ><span class="muted">每 15 秒自动刷新</span>
  </div>
  <n-spin :show="loading && !workers.length"
    ><div class="worker-grid">
      <button
        v-for="worker in workers"
        :key="worker.worker_id"
        class="worker-card panel"
        :class="{ selected: selected?.worker_id === worker.worker_id }"
        @click="select(worker)"
      >
        <div class="worker-card-top">
          <span class="worker-symbol">W</span
          ><span class="worker-online"
            ><i class="status-dot success" />ONLINE</span
          >
        </div>
        <strong>{{ worker.hostname }}</strong
        ><span class="mini-id">{{ worker.worker_id }}</span>
        <div class="worker-util">
          <span
            >运行中 <b>{{ worker.running }} / {{ worker.capacity }}</b></span
          ><n-progress
            type="line"
            :percentage="
              worker.capacity ? (worker.running / worker.capacity) * 100 : 0
            "
            :show-indicator="false"
            :height="5"
            color="#e59b42"
          />
        </div>
        <div class="worker-meta">
          <span>V{{ worker.runtime_version }}</span
          ><span>{{ date(worker.heartbeat_at) }}</span>
        </div>
      </button>
    </div>
    <div v-if="!workers.length" class="panel empty-copy">
      暂无在线 Worker
    </div></n-spin
  >
  <div v-if="selected" class="panel" style="margin-top: 20px">
    <div class="panel-head">
      <h3>当前运行 · {{ selected.hostname }}</h3>
      <span class="mini-id">{{ selected.worker_id }}</span>
    </div>
    <div class="panel-body">
      <div
        v-for="run in selected.current_runs || []"
        :key="run"
        class="worker-run"
        @click="router.push(`/runs/${run}`)"
      >
        <span class="status-dot info" /><span class="mono">{{ run }}</span
        ><span>查看 →</span>
      </div>
      <div v-if="!selected.current_runs?.length" class="empty-copy">
        当前没有执行中的 Run
      </div>
    </div>
  </div>
</template>
<style scoped>
.worker-summary {
  display: flex;
  gap: 15px;
  align-items: center;
  padding: 18px 22px;
  margin-bottom: 19px;
  font-size: 12px;
}
.worker-summary span:last-child {
  margin-left: auto;
  font-size: 10px;
}
.worker-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 15px;
}
.worker-card {
  display: flex;
  flex-direction: column;
  align-items: start;
  text-align: left;
  padding: 20px;
  border-radius: 9px;
  color: var(--ink);
  cursor: pointer;
}
.worker-card.selected {
  border-color: #e5a250;
}
.worker-card-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  width: 100%;
  margin-bottom: 17px;
}
.worker-symbol {
  display: grid;
  place-items: center;
  width: 31px;
  height: 31px;
  background: #edf2f2;
  border: 1px solid var(--border);
  font-family: "IBM Plex Mono", monospace;
  font-size: 13px;
}
.worker-online {
  font-family: "IBM Plex Mono", monospace;
  font-size: 9px;
  color: #399b6a;
}
.worker-card > strong {
  font-size: 14px;
  margin-bottom: 3px;
}
.worker-util {
  width: 100%;
  margin: 24px 0 17px;
}
.worker-util > span {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--muted);
  margin-bottom: 9px;
}
.worker-util b {
  color: var(--ink);
  font-family: "IBM Plex Mono", monospace;
}
.worker-meta {
  display: flex;
  justify-content: space-between;
  border-top: 1px solid var(--border);
  padding-top: 14px;
  width: 100%;
  color: var(--muted);
  font-size: 10px;
}
.worker-run {
  display: flex;
  gap: 10px;
  align-items: center;
  padding: 13px 0;
  border-bottom: 1px solid var(--border);
  cursor: pointer;
  font-size: 11px;
}
.worker-run span:last-child {
  margin-left: auto;
  color: #a77337;
}
@media (max-width: 1100px) {
  .worker-grid {
    grid-template-columns: repeat(2, 1fr);
  }
}
@media (max-width: 700px) {
  .worker-grid {
    grid-template-columns: 1fr;
  }
}
</style>
