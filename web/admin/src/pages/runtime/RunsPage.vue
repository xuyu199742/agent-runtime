<script setup lang="ts">
import { computed, h, ref } from "vue";
import { useRouter } from "vue-router";
import { NButton, NInput, NSelect } from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import StatusLabel from "../../components/StatusLabel.vue";
import type { RecordData } from "../../api/client";

const router = useRouter(),
  status = ref<string | null>(null),
  agentId = ref(""),
  workerId = ref(""),
  errorCode = ref("");
const params = computed(() => ({
  status: status.value,
  agent_id: agentId.value || undefined,
  worker_id: workerId.value || undefined,
  error_code: errorCode.value || undefined,
}));
const date = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString("zh-CN", { hour12: false })
    : "—";
const columns: DataTableColumns<RecordData> = [
  {
    title: "Run ID",
    key: "id",
    render: (row) =>
      h("span", { class: "mini-id" }, String(row.id).slice(0, 18) + "…"),
  },
  {
    title: "状态",
    key: "status",
    render: (row) => h(StatusLabel, { value: String(row.status) }),
  },
  {
    title: "Agent",
    key: "agent",
    render: (row) => String((row.agent as RecordData)?.name || "—"),
  },
  { title: "Worker", key: "worker_id", ellipsis: { tooltip: true } },
  { title: "错误", key: "error_code" },
  {
    title: "创建时间",
    key: "created_at",
    render: (row) => date(row.created_at),
  },
  {
    title: "操作",
    key: "action",
    render: (row) =>
      h(
        NButton,
        {
          size: "tiny",
          quaternary: true,
          onClick: () => router.push(`/runs/${row.id}`),
        },
        { default: () => "查看详情 →" },
      ),
  },
];
</script>
<template>
  <data-list
    eyebrow="EXECUTION / RUNS"
    title="运行记录"
    description="按状态、Agent、Worker 和错误码定位每一次执行。"
    endpoint="/api/v1/admin/runs"
    :columns="columns"
    :params="params"
    ><template #filters
      ><n-select
        v-model:value="status"
        clearable
        placeholder="全部状态"
        style="width: 145px"
        :options="
          [
            'PENDING',
            'RUNNING',
            'WAITING',
            'COMPLETED',
            'FAILED',
            'CANCELLED',
          ].map((value) => ({ label: value, value }))
        " /><n-input
        v-model:value="agentId"
        clearable
        placeholder="Agent ID"
        style="width: 145px" /><n-input
        v-model:value="workerId"
        clearable
        placeholder="Worker ID"
        style="width: 145px" /><n-input
        v-model:value="errorCode"
        clearable
        placeholder="错误码"
        style="width: 120px" /></template
  ></data-list>
</template>
