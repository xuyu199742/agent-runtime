<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  NButton,
  NDescriptions,
  NDescriptionsItem,
  NIcon,
  NTabPane,
  NTabs,
  NTimeline,
  NTimelineItem,
  useDialog,
  useMessage,
} from "naive-ui";
import { ArrowBackOutline, RefreshOutline } from "@vicons/ionicons5";
import PageHeader from "../../components/PageHeader.vue";
import StatusLabel from "../../components/StatusLabel.vue";
import { api, download, type Page, type RecordData } from "../../api/client";
import { useAuthStore } from "../../stores/auth";

const route = useRoute(),
  router = useRouter(),
  auth = useAuthStore(),
  message = useMessage(),
  dialog = useDialog();
const id = computed(() => String(route.params.id)),
  loading = ref(false),
  tab = ref("overview");
const run = ref<RecordData | null>(null),
  spec = ref<RecordData | null>(null),
  timeline = ref<RecordData[]>([]),
  timelinePage = ref(1),
  timelineTotal = ref(0),
  executions = ref<RecordData[]>([]),
  artifacts = ref<RecordData[]>([]);
const date = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString("zh-CN", { hour12: false })
    : "—";
const json = (value: unknown) => JSON.stringify(value, null, 2);
const recoveryErrorText = (code: unknown) => {
  const messages: Record<string, string> = {
    APPROVAL_RECOVERY_LOST:
      "审批检查点丢失，Run 已安全停止。请核对审批与工具记录。",
    TOOL_RESULT_UNAVAILABLE:
      "已完成的 Tool 缺少可重放结果，Run 已安全停止。请核对工具事实。",
  };
  return (
    messages[String(code)] || "请核对时间线与执行事实，再决定是否发起新的 Run。"
  );
};
async function load() {
  loading.value = true;
  try {
    const [detail, snapshot, timelineResult, tools] = await Promise.all([
      api.get<RecordData>(`/api/v1/admin/runs/${id.value}`),
      api.get<RecordData>(`/api/v1/admin/runs/${id.value}/execution-spec`),
      api.get<Page<RecordData>>(
        `/api/v1/admin/runs/${id.value}/timeline?page_size=100`,
      ),
      api.get<RecordData[]>(`/api/v1/admin/runs/${id.value}/tool-executions`),
    ]);
    run.value = detail;
    spec.value = snapshot;
    timelinePage.value = 1;
    timelineTotal.value = timelineResult.total;
    timeline.value = timelineResult.items;
    executions.value = tools;
    artifacts.value = auth.can("artifact:view")
      ? (
          await api.get<Page<RecordData>>(
            `/api/v1/admin/runs/${id.value}/artifacts`,
          )
        ).items
      : [];
  } catch (error) {
    message.error(error instanceof Error ? error.message : "Run 加载失败");
  } finally {
    loading.value = false;
  }
}
async function loadMoreTimeline() {
  try {
    const nextPage = timelinePage.value + 1;
    const result = await api.get<Page<RecordData>>(
      `/api/v1/admin/runs/${id.value}/timeline?page=${nextPage}&page_size=100`,
    );
    timeline.value.push(...result.items);
    timelinePage.value = nextPage;
    timelineTotal.value = result.total;
  } catch (error) {
    message.error(error instanceof Error ? error.message : "Timeline 加载失败");
  }
}
onMounted(load);
async function operation(kind: "cancel" | "retry") {
  try {
    const result = await api.post<RecordData>(
      `/api/v1/admin/runs/${id.value}/${kind}`,
    );
    message.success(kind === "retry" ? "已创建重试 Run" : "取消请求已提交");
    if (kind === "retry") router.push(`/runs/${result.id}`);
    else load();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "操作失败");
  }
}
function confirm(kind: "cancel" | "retry") {
  dialog.warning({
    title: kind === "cancel" ? "取消 Run" : "重试 Run",
    content:
      kind === "cancel"
        ? "将终止当前执行。"
        : "将创建新的 Run。请先核对原 Run 的时间线和工具执行结果。",
    positiveText: "确认",
    negativeText: "返回",
    onPositiveClick: () => operation(kind),
  });
}
</script>
<template>
  <page-header
    eyebrow="EXECUTION / RUN DETAIL"
    :title="`Run ${id.slice(0, 8)}`"
    description="检查执行快照、生命周期与工具调用。"
    ><n-button secondary @click="router.push('/runs')"
      ><template #icon><n-icon :component="ArrowBackOutline" /></template
      >返回列表</n-button
    ><n-button secondary :loading="loading" @click="load"
      ><template #icon><n-icon :component="RefreshOutline" /></template
      >刷新</n-button
    ><n-button
      v-if="
        run &&
        ['PENDING', 'RUNNING', 'WAITING'].includes(String(run.status)) &&
        auth.can('run:cancel')
      "
      type="warning"
      @click="confirm('cancel')"
      >取消 Run</n-button
    ><n-button
      v-if="
        run &&
        ['FAILED', 'CANCELLED'].includes(String(run.status)) &&
        auth.can('run:retry')
      "
      type="primary"
      @click="confirm('retry')"
      >重试 Run</n-button
    ></page-header
  >
  <div v-if="run" class="panel">
    <div class="panel-head">
      <h3>运行状态</h3>
      <status-label :value="String(run.status)" />
    </div>
    <div class="panel-body">
      <div class="detail-grid">
        <dl
          v-for="item in [
            { label: 'Run ID', value: run.id },
            { label: 'Agent', value: (run.agent as RecordData)?.name },
            { label: 'Worker', value: run.worker_id },
            { label: 'Runtime', value: run.runtime_version },
            { label: 'Revision / Spec', value: run.execution_spec_id },
            { label: 'Parent Run', value: run.parent_run_id },
            { label: 'Created', value: date(run.created_at) },
            { label: 'Started', value: date(run.started_at) },
            { label: 'Completed', value: date(run.completed_at) },
          ]"
          :key="item.label"
          class="detail-pair"
        >
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value || "—" }}</dd>
        </dl>
      </div>
    </div>
  </div>
  <n-tabs v-model:value="tab" type="line" animated style="margin-top: 24px"
    ><n-tab-pane name="overview" tab="总览"
      ><div class="panel">
        <div class="panel-body">
          <div class="detail-section">
            <h3>最终回答</h3>
            <div class="answer-box">{{ run?.answer || "暂无最终回答" }}</div>
          </div>
          <div v-if="run?.error_code" class="detail-section">
            <h3>错误</h3>
            <status-label :value="String(run.error_code)" />
            <p>{{ recoveryErrorText(run.error_code) }}</p>
          </div>
        </div>
      </div></n-tab-pane
    ><n-tab-pane name="timeline" :tab="`Timeline · ${timelineTotal}`"
      ><div class="panel">
        <div class="panel-body">
          <n-timeline v-if="timeline.length"
            ><n-timeline-item
              v-for="event in timeline"
              :key="String(event.sequence)"
              :title="`#${event.sequence} · ${event.event_type}`"
              :content="
                [
                  event.summary,
                  event.attempt && Number(event.attempt) > 1
                    ? `尝试 ${event.attempt}`
                    : null,
                  event.ref_type && event.ref_id
                    ? `${event.ref_type}: ${event.ref_id}`
                    : null,
                  event.duration != null ? `${event.duration} ms` : null,
                ]
                  .filter(Boolean)
                  .join(' · ')
              "
              :time="date(event.created_at)"
              :type="
                String(event.event_type).includes('failed') ||
                String(event.event_type).includes('rejected')
                  ? 'error'
                  : String(event.event_type).includes('completed') ||
                      String(event.event_type).includes('approved')
                    ? 'success'
                    : 'info'
              "
          /></n-timeline>
          <div v-else class="empty-copy">暂无生命周期记录</div>
          <n-button
            v-if="timeline.length < timelineTotal"
            secondary
            @click="loadMoreTimeline"
            >加载更多</n-button
          >
        </div>
      </div></n-tab-pane
    ><n-tab-pane name="spec" tab="Execution Spec"
      ><div class="panel">
        <div class="panel-body">
          <pre class="code-box">{{ json(spec) }}</pre>
        </div>
      </div></n-tab-pane
    ><n-tab-pane name="tools" :tab="`Tool Executions · ${executions.length}`"
      ><div class="panel">
        <div class="panel-body">
          <div
            v-for="tool in executions"
            :key="String(tool.id)"
            class="execution-card"
          >
            <div>
              <strong>{{ tool.tool_name }}</strong
              ><status-label :value="String(tool.status)" />
            </div>
            <div class="detail-grid">
              <dl
                v-for="key in [
                  'tool_call_id',
                  'effect_type',
                  'idempotency_key',
                  'attempt',
                  'error_code',
                  'started_at',
                  'completed_at',
                ]"
                :key="key"
                class="detail-pair"
              >
                <dt>{{ key }}</dt>
                <dd>{{ tool[key] || "—" }}</dd>
              </dl>
            </div>
          </div>
          <div v-if="!executions.length" class="empty-copy">
            本次运行未调用工具
          </div>
        </div>
      </div></n-tab-pane
    ><n-tab-pane
      v-if="auth.can('artifact:view')"
      name="artifacts"
      :tab="`Artifacts · ${artifacts.length}`"
      ><div class="panel">
        <div class="panel-body">
          <div
            v-for="artifact in artifacts"
            :key="String(artifact.id)"
            class="execution-card"
          >
            <strong>{{ artifact.name }}</strong
            ><span class="muted"
              >{{ artifact.mime_type }} · {{ artifact.size }} bytes</span
            ><n-button
              size="small"
              @click="
                download(
                  `/api/v1/admin/artifacts/${artifact.id}/download`,
                  String(artifact.name),
                )
              "
              >下载</n-button
            >
          </div>
          <div v-if="!artifacts.length" class="empty-copy">
            本次运行暂无 Artifact
          </div>
        </div>
      </div></n-tab-pane
    ></n-tabs
  >
</template>
<style scoped>
.answer-box {
  white-space: pre-wrap;
  line-height: 1.8;
  color: var(--ink);
  font-size: 13px;
}
.execution-card {
  padding: 17px 0;
  border-bottom: 1px solid var(--border);
}
.execution-card > div:first-child {
  display: flex;
  gap: 20px;
  align-items: center;
  margin-bottom: 14px;
}
.execution-card > span {
  margin: 0 20px;
  font-size: 11px;
}
.execution-card:last-child {
  border-bottom: 0;
}
</style>
