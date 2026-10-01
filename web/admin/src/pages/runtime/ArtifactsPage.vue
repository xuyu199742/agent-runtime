<script setup lang="ts">
import { computed, h, ref } from "vue";
import {
  NButton,
  NInput,
  NDrawer,
  NDrawerContent,
  NDescriptions,
  NDescriptionsItem,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import { api, download, type RecordData } from "../../api/client";

const userId = ref(""),
  params = computed(() => ({ user_id: userId.value || undefined })),
  show = ref(false),
  selected = ref<RecordData | null>(null);
const date = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString("zh-CN", { hour12: false })
    : "—";
async function open(row: RecordData) {
  selected.value = await api.get<RecordData>(
    `/api/v1/admin/artifacts/${row.id}`,
  );
  show.value = true;
}
const columns: DataTableColumns<RecordData> = [
  {
    title: "文件名",
    key: "name",
    render: (row) => h("strong", { style: "font-size:12px" }, String(row.name)),
  },
  { title: "类型", key: "mime_type" },
  {
    title: "大小",
    key: "size",
    render: (row) => `${(Number(row.size) / 1024).toFixed(1)} KB`,
  },
  {
    title: "Conversation",
    key: "conversation_id",
    render: (row) =>
      h("span", { class: "mini-id" }, String(row.conversation_id).slice(0, 18)),
  },
  {
    title: "Run",
    key: "run_id",
    render: (row) =>
      h(
        "span",
        { class: "mini-id" },
        row.run_id ? String(row.run_id).slice(0, 18) : "—",
      ),
  },
  {
    title: "创建时间",
    key: "created_at",
    render: (row) => date(row.created_at),
  },
  {
    title: "操作",
    key: "action",
    render: (row) =>
      h("div", { style: "display:flex;gap:4px" }, [
        h(
          NButton,
          { size: "tiny", quaternary: true, onClick: () => open(row) },
          { default: () => "详情" },
        ),
        h(
          NButton,
          {
            size: "tiny",
            quaternary: true,
            onClick: () =>
              download(
                `/api/v1/admin/artifacts/${row.id}/download`,
                String(row.name),
              ),
          },
          { default: () => "下载" },
        ),
      ]),
  },
];
</script>
<template>
  <data-list
    eyebrow="EXECUTION / ARTIFACTS"
    title="文件产物"
    description="按用户查询文件元数据并安全下载，不展示内部存储键。"
    endpoint="/api/v1/admin/artifacts"
    :columns="columns"
    :params="params"
    ><template #filters
      ><n-input
        v-model:value="userId"
        clearable
        placeholder="用户 ID"
        style="width: 220px" /></template></data-list
  ><n-drawer v-model:show="show" :width="530"
    ><n-drawer-content title="Artifact 详情" closable
      ><n-descriptions v-if="selected" :column="1" bordered
        ><n-descriptions-item
          v-for="key in [
            'id',
            'name',
            'type',
            'mime_type',
            'size',
            'conversation_id',
            'run_id',
            'message_id',
            'created_at',
          ]"
          :key="key"
          :label="key"
          >{{ selected[key] || "—" }}</n-descriptions-item
        ></n-descriptions
      >
      <pre
        v-if="selected?.metadata"
        class="code-box"
        style="margin-top: 20px"
        >{{ JSON.stringify(selected.metadata, null, 2) }}</pre>
      <template #footer
        ><n-button
          v-if="selected"
          type="primary"
          @click="
            download(
              `/api/v1/admin/artifacts/${selected.id}/download`,
              String(selected.name),
            )
          "
          >下载文件</n-button
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
