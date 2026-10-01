<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { NButton, NIcon, NSpin, useMessage } from "naive-ui";
import { RefreshOutline, ArrowForwardOutline } from "@vicons/ionicons5";
import { useRouter } from "vue-router";
import { api } from "../api/client";

interface Dashboard {
  today_runs: number;
  running: number;
  waiting: number;
  failed: number;
  average_duration_ms: number | null;
  success_rate: number | null;
  run_trend: { day: string; status: string; count: number }[];
  error_trend: { code: string; count: number }[];
  model_usage: { model: string; count: number }[];
  recent_failed: {
    id: string;
    error_code: string | null;
    created_at: string;
  }[];
  waiting_approvals: { run_id: string; waiting_at: string }[];
  worker_capacity: number;
  worker_running: number;
  queue_depth: number;
  oldest_pending_at: string | null;
}
const data = ref<Dashboard | null>(null),
  loading = ref(false),
  message = useMessage(),
  router = useRouter();
const metrics = computed(() =>
  data.value
    ? [
        ["今日运行", String(data.value.today_runs).padStart(2, "0")],
        ["运行中", String(data.value.running).padStart(2, "0")],
        ["等待审批", String(data.value.waiting).padStart(2, "0")],
        ["今日失败", String(data.value.failed).padStart(2, "0")],
        [
          "平均耗时",
          data.value.average_duration_ms == null
            ? "—"
            : `${(data.value.average_duration_ms / 1000).toFixed(1)}s`,
        ],
        [
          "成功率",
          data.value.success_rate == null
            ? "—"
            : `${(data.value.success_rate * 100).toFixed(1)}%`,
        ],
      ]
    : [],
);
const days = computed(() => {
  const grouped = new Map<
    string,
    { day: string; completed: number; failed: number }
  >();
  for (const item of data.value?.run_trend || []) {
    const row = grouped.get(item.day) || {
      day: item.day,
      completed: 0,
      failed: 0,
    };
    if (item.status === "COMPLETED") row.completed += item.count;
    if (item.status === "FAILED") row.failed += item.count;
    grouped.set(item.day, row);
  }
  return [...grouped.values()].slice(-7);
});
const maxDay = computed(() =>
  Math.max(1, ...days.value.map((day) => day.completed + day.failed)),
);
async function load() {
  loading.value = true;
  try {
    data.value = await api.get<Dashboard>("/api/v1/admin/dashboard");
  } catch (error) {
    message.error(error instanceof Error ? error.message : "统计加载失败");
  } finally {
    loading.value = false;
  }
}
onMounted(load);
const date = (value: string) =>
  new Date(value).toLocaleString("zh-CN", { hour12: false });
</script>

<template>
  <div class="page-head">
    <div>
      <div class="page-eyebrow">OVERVIEW / RUNTIME</div>
      <h1 class="page-title">运行工作台</h1>
      <p class="page-description">
        实时观察 Agent 执行、Worker 容量与任务趋势。
      </p>
    </div>
    <div class="page-actions">
      <n-button secondary :loading="loading" @click="load"
        ><template #icon><n-icon :component="RefreshOutline" /></template
        >刷新数据</n-button
      >
    </div>
  </div>
  <n-spin :show="loading && !data">
    <template v-if="data">
      <div class="metric-grid">
        <div
          v-for="([label, value], index) in metrics"
          :key="label"
          class="panel metric-card"
          :class="{ highlight: index === 0 }"
        >
          <div class="metric-label">{{ label }}</div>
          <div class="metric-value">{{ value }}</div>
          <div class="metric-rule" />
        </div>
      </div>
      <div class="dashboard-grid">
        <div class="panel chart-panel">
          <div class="panel-head">
            <h3>运行趋势</h3>
            <span class="muted mono" style="font-size: 10px"
              >最近 7 天 · UTC</span
            >
          </div>
          <div class="panel-body">
            <div v-if="days.length" class="bar-chart">
              <div v-for="day in days" :key="day.day" class="bar-day">
                <div class="bar-stack">
                  <div
                    class="bar-segment failed"
                    :style="{
                      height: `${Math.max(2, (day.failed / maxDay) * 150)}px`,
                    }"
                    :title="`失败 ${day.failed}`"
                  />
                  <div
                    class="bar-segment"
                    :style="{
                      height: `${Math.max(2, (day.completed / maxDay) * 150)}px`,
                    }"
                    :title="`完成 ${day.completed}`"
                  />
                </div>
                <div class="bar-label">{{ day.day.slice(5) }}</div>
              </div>
            </div>
            <div v-else class="empty-copy">暂无运行记录</div>
            <div class="bar-legend"><span>已完成</span><span>失败</span></div>
          </div>
        </div>
        <div class="panel chart-panel">
          <div class="panel-head">
            <h3>运行环境</h3>
            <n-button text size="tiny" @click="router.push('/workers')"
              >查看 Workers <n-icon :component="ArrowForwardOutline"
            /></n-button>
          </div>
          <div class="panel-body">
            <div class="runtime-gauges">
              <div class="runtime-gauge">
                <div>
                  <small>WORKER CAPACITY</small
                  ><strong
                    >{{ data.worker_running }}
                    <em>/ {{ data.worker_capacity }}</em></strong
                  >
                </div>
                <div class="gauge-track">
                  <div
                    :style="{
                      width: `${data.worker_capacity ? (data.worker_running / data.worker_capacity) * 100 : 0}%`,
                    }"
                  />
                </div>
              </div>
              <div class="runtime-gauge">
                <div>
                  <small>QUEUE DEPTH</small
                  ><strong>{{ data.queue_depth }}</strong>
                </div>
                <div class="gauge-track">
                  <div
                    :style="{
                      width: `${Math.min(100, data.queue_depth * 10)}%`,
                    }"
                  />
                </div>
              </div>
              <div class="runtime-gauge">
                <div>
                  <small>OLDEST PENDING</small
                  ><strong style="font-size: 13px">{{
                    data.oldest_pending_at ? date(data.oldest_pending_at) : "—"
                  }}</strong>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
      <div class="dashboard-grid" style="margin-top: 18px">
        <div class="panel">
          <div class="panel-head">
            <h3>最近失败的运行</h3>
            <n-button text size="tiny" @click="router.push('/runs')"
              >全部 Runs <n-icon :component="ArrowForwardOutline"
            /></n-button>
          </div>
          <div class="panel-body">
            <ul v-if="data.recent_failed.length" class="top-list">
              <li
                v-for="(run, index) in data.recent_failed.slice(0, 6)"
                :key="run.id"
                style="cursor: pointer"
                @click="router.push(`/runs/${run.id}`)"
              >
                <span class="list-index">{{
                  String(index + 1).padStart(2, "0")
                }}</span
                ><span class="mini-id">{{ run.id.slice(0, 18) }}…</span
                ><span class="muted">{{ run.error_code || "未知错误" }}</span
                ><strong>→</strong>
              </li>
            </ul>
            <div v-else class="empty-copy">最近没有失败的 Run</div>
          </div>
        </div>
        <div class="panel">
          <div class="panel-head">
            <h3>模型调用分布</h3>
            <span class="muted mono" style="font-size: 10px">LAST 7 DAYS</span>
          </div>
          <div class="panel-body">
            <ul v-if="data.model_usage.length" class="top-list">
              <li
                v-for="(model, index) in data.model_usage.slice(0, 6)"
                :key="index"
              >
                <span class="list-index">{{
                  String(index + 1).padStart(2, "0")
                }}</span
                ><span>{{ model.model || "未命名模型" }}</span
                ><strong>{{ model.count }}</strong>
              </li>
            </ul>
            <div v-else class="empty-copy">暂无模型使用数据</div>
          </div>
        </div>
      </div>
    </template>
  </n-spin>
</template>

<style scoped>
.runtime-gauges {
  display: grid;
  gap: 25px;
  padding: 4px 0;
}
.runtime-gauge > div:first-child {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
}
.runtime-gauge small {
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  color: var(--muted);
  letter-spacing: 0.08em;
}
.runtime-gauge strong {
  font-family: "IBM Plex Mono", monospace;
  font-size: 21px;
  color: var(--ink);
}
.runtime-gauge em {
  font-style: normal;
  color: var(--muted);
  font-size: 12px;
}
.gauge-track {
  height: 5px;
  background: var(--border);
  margin-top: 11px;
  border-radius: 9px;
  overflow: hidden;
}
.gauge-track > div {
  height: 100%;
  background: var(--accent);
  border-radius: 9px;
}
</style>
