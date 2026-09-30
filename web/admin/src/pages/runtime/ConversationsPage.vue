<script setup lang="ts">
import { h, ref } from "vue";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NTabPane,
  NTabs,
  useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import { api, download, type Page, type RecordData } from "../../api/client";
import { useAuthStore } from "../../stores/auth";

type Conversation = RecordData & {
  id: string;
  title: string;
  user_id: string;
  agent: { id: string; name: string };
  created_at: string;
  last_active_at: string;
};
const message = useMessage(),
  auth = useAuthStore(),
  show = ref(false),
  selected = ref<RecordData | null>(null),
  messages = ref<RecordData[]>([]),
  artifacts = ref<RecordData[]>([]),
  tab = ref("messages");
const date = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString("zh-CN", { hour12: false })
    : "—";
async function open(row: Conversation) {
  show.value = true;
  selected.value = row;
  messages.value = [];
  artifacts.value = [];
  try {
    const [detail, history] = await Promise.all([
      api.get<RecordData>(`/api/v1/admin/conversations/${row.id}`),
      api.get<RecordData[]>(
        `/api/v1/admin/conversations/${row.id}/messages?limit=100`,
      ),
    ]);
    selected.value = detail;
    messages.value = history;
    if (auth.can("artifact:view"))
      artifacts.value = (
        await api.get<Page<RecordData>>(
          `/api/v1/admin/conversations/${row.id}/artifacts`,
        )
      ).items;
  } catch (error) {
    message.error(error instanceof Error ? error.message : "会话加载失败");
  }
}
const columns: DataTableColumns<RecordData> = [
  {
    title: "会话",
    key: "id",
    render: (row) =>
      h("div", [
        h(
          "strong",
          { style: "font-size:12px" },
          String(row.title || "未命名会话"),
        ),
        h("div", { class: "mini-id" }, String(row.id).slice(0, 18) + "…"),
      ]),
  },
  {
    title: "用户",
    key: "user_id",
    render: (row) =>
      h("span", { class: "mini-id" }, String(row.user_id).slice(0, 18)),
  },
  {
    title: "Agent",
    key: "agent",
    render: (row) => String((row.agent as RecordData)?.name || "—"),
  },
  {
    title: "最近活动",
    key: "last_active_at",
    render: (row) => date(row.last_active_at),
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
      h(
        NButton,
        {
          size: "tiny",
          quaternary: true,
          onClick: () => open(row as Conversation),
        },
        { default: () => "查看会话 →" },
      ),
  },
];
</script>
<template>
  <data-list
    eyebrow="EXECUTION / CONVERSATIONS"
    title="会话"
    description="查看用户历史消息与关联 Artifact。历史内容只读。"
    endpoint="/api/v1/admin/conversations"
    :columns="columns"
  /><n-drawer v-model:show="show" :width="720"
    ><n-drawer-content :title="String(selected?.title || '会话详情')" closable
      ><div v-if="selected" class="detail-grid">
        <dl
          v-for="item in [
            { label: 'Conversation ID', value: selected.id },
            { label: 'User ID', value: selected.user_id },
            { label: 'Agent', value: (selected.agent as RecordData)?.name },
            { label: 'Created', value: date(selected.created_at) },
            { label: 'Last Active', value: date(selected.last_active_at) },
            {
              label: 'Statistics',
              value: JSON.stringify(selected.statistics || {}),
            },
          ]"
          :key="item.label"
          class="detail-pair"
        >
          <dt>{{ item.label }}</dt>
          <dd>{{ item.value || "—" }}</dd>
        </dl>
      </div>
      <n-tabs v-model:value="tab" type="line" style="margin-top: 22px"
        ><n-tab-pane name="messages" :tab="`消息 · ${messages.length}`"
          ><div
            v-for="item in messages"
            :key="String(item.id)"
            class="message-row"
          >
            <div>
              <strong>{{ item.role }}</strong
              ><span class="muted">{{ date(item.created_at) }}</span>
            </div>
            <p>{{ item.content }}</p>
            <span class="mini-id">{{ item.id }}</span>
          </div>
          <div v-if="!messages.length" class="empty-copy">
            暂无消息
          </div></n-tab-pane
        ><n-tab-pane
          v-if="auth.can('artifact:view')"
          name="artifacts"
          :tab="`Artifacts · ${artifacts.length}`"
          ><div
            v-for="artifact in artifacts"
            :key="String(artifact.id)"
            class="message-row"
          >
            <div>
              <strong>{{ artifact.name }}</strong
              ><span class="muted"
                >{{ artifact.mime_type }} · {{ artifact.size }} bytes</span
              ><n-button
                size="tiny"
                @click="
                  download(
                    `/api/v1/admin/artifacts/${artifact.id}/download`,
                    String(artifact.name),
                  )
                "
                >下载</n-button
              >
            </div>
          </div>
          <div v-if="!artifacts.length" class="empty-copy">
            暂无文件产物
          </div></n-tab-pane
        ></n-tabs
      ></n-drawer-content
    ></n-drawer
  >
</template>
<style scoped>
.message-row {
  padding: 16px 0;
  border-bottom: 1px solid var(--border);
}
.message-row > div:first-child {
  display: flex;
  gap: 15px;
  align-items: center;
  font-size: 11px;
}
.message-row p {
  white-space: pre-wrap;
  font-size: 12px;
  line-height: 1.75;
  margin: 10px 0;
  color: var(--ink);
}
.message-row .muted {
  font-size: 10px;
}
</style>
