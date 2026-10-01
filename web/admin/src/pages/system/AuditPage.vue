<script setup lang="ts">
import { h, ref } from "vue";
import { NButton } from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import DetailDrawer from "../../components/DetailDrawer.vue";
import type { RecordData } from "../../api/client";

const selected = ref<RecordData | null>(null),
  show = ref(false);
const date = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString("zh-CN", { hour12: false })
    : "—";
const columns: DataTableColumns<RecordData> = [
  { title: "时间", key: "created_at", render: (row) => date(row.created_at) },
  {
    title: "操作",
    key: "action",
    render: (row) =>
      h("strong", { style: "font-size:11px" }, String(row.action)),
  },
  {
    title: "操作者",
    key: "actor_id",
    render: (row) =>
      h("span", { class: "mini-id" }, String(row.actor_id || "—").slice(0, 18)),
  },
  { title: "对象", key: "target_type" },
  {
    title: "对象 ID",
    key: "target_id",
    render: (row) =>
      h(
        "span",
        { class: "mini-id" },
        String(row.target_id || "—").slice(0, 18),
      ),
  },
  {
    title: "请求 ID",
    key: "request_id",
    render: (row) =>
      h(
        "span",
        { class: "mini-id" },
        String(row.request_id || "—").slice(0, 18),
      ),
  },
  {
    title: "操作",
    key: "detail",
    render: (row) =>
      h(
        NButton,
        {
          size: "tiny",
          quaternary: true,
          onClick: () => {
            selected.value = row;
            show.value = true;
          },
        },
        { default: () => "详情" },
      ),
  },
];
const fields = [
  "id",
  "actor_id",
  "action",
  "target_type",
  "target_id",
  "request_id",
  "details",
  "created_at",
].map((key) => ({ label: key, key }));
</script>
<template>
  <data-list
    eyebrow="SYSTEM / AUDIT"
    title="审计日志"
    description="追溯管理员的重要写操作与审批决策。"
    endpoint="/api/v1/admin/audit-logs"
    :columns="columns"
  /><detail-drawer
    v-model:open="show"
    title="审计记录"
    :row="selected"
    :fields="fields"
  />
</template>
