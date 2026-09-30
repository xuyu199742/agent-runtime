<script setup lang="ts">
import { h, ref } from "vue";
import { useRouter } from "vue-router";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NDescriptions,
  NDescriptionsItem,
  NSpace,
  NSelect,
  useDialog,
  useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import StatusLabel from "../../components/StatusLabel.vue";
import { api, type RecordData } from "../../api/client";
import { useAuthStore } from "../../stores/auth";

const auth = useAuthStore(),
  message = useMessage(),
  dialog = useDialog(),
  router = useRouter(),
  list = ref<InstanceType<typeof DataList> | null>(null);
const status = ref<string | null>(null),
  show = ref(false),
  selected = ref<RecordData | null>(null);
async function open(row: RecordData) {
  show.value = true;
  try {
    selected.value = await api.get<RecordData>(
      `/api/v1/admin/approvals/${row.id}`,
    );
  } catch (error) {
    message.error(error instanceof Error ? error.message : "加载失败");
  }
}
async function decide(row: RecordData, kind: "approve" | "reject") {
  dialog.warning({
    title: kind === "approve" ? "批准执行" : "拒绝执行",
    content: `确认处理 ${row.tool_name || "Tool"} 的调用？该决定会继续影响 Run。`,
    positiveText: kind === "approve" ? "批准" : "拒绝",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await api.post(`/api/v1/admin/approvals/${row.id}/${kind}`);
        message.success("审批已处理");
        show.value = false;
        list.value?.reload();
      } catch (error) {
        message.error(error instanceof Error ? error.message : "审批失败");
      }
    },
  });
}
const date = (value: unknown) =>
  value
    ? new Date(String(value)).toLocaleString("zh-CN", { hour12: false })
    : "—";
const columns: DataTableColumns<RecordData> = [
  {
    title: "工具",
    key: "tool_name",
    render: (row) =>
      h("strong", { style: "font-size:12px" }, String(row.tool_name)),
  },
  { title: "风险", key: "risk" },
  {
    title: "状态",
    key: "status",
    render: (row) => h(StatusLabel, { value: String(row.status) }),
  },
  {
    title: "Run",
    key: "run_id",
    render: (row) =>
      h("span", { class: "mini-id" }, String(row.run_id).slice(0, 18)),
  },
  {
    title: "等待时间",
    key: "created_at",
    render: (row) => date(row.created_at),
  },
  {
    title: "操作",
    key: "action",
    render: (row) =>
      h(
        NSpace,
        { size: 4 },
        {
          default: () => [
            h(
              NButton,
              { size: "tiny", quaternary: true, onClick: () => open(row) },
              { default: () => "详情" },
            ),
            row.status === "PENDING" && auth.can("approval:approve")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    type: "primary",
                    onClick: () => decide(row, "approve"),
                  },
                  { default: () => "批准" },
                )
              : null,
            row.status === "PENDING" && auth.can("approval:approve")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    type: "error",
                    ghost: true,
                    onClick: () => decide(row, "reject"),
                  },
                  { default: () => "拒绝" },
                )
              : null,
          ],
        },
      ),
  },
];
</script>
<template>
  <data-list
    ref="list"
    eyebrow="EXECUTION / APPROVALS"
    title="人工审批"
    description="查看等待中的高风险工具调用，并记录每次决策。"
    endpoint="/api/v1/admin/approvals"
    :columns="columns"
    :params="{ status }"
    ><template #filters
      ><n-select
        v-model:value="status"
        clearable
        placeholder="全部状态"
        style="width: 150px"
        :options="
          ['PENDING', 'APPROVED', 'REJECTED', 'CANCELLED'].map((value) => ({
            label: value,
            value,
          }))
        " /></template></data-list
  ><n-drawer v-model:show="show" :width="560"
    ><n-drawer-content title="审批详情" closable
      ><n-descriptions v-if="selected" :column="1" bordered
        ><n-descriptions-item
          v-for="key in [
            'id',
            'run_id',
            'tool_name',
            'title',
            'description',
            'risk',
            'status',
            'created_at',
            'decided_at',
          ]"
          :key="key"
          :label="key"
          >{{ selected[key] || "—" }}</n-descriptions-item
        ></n-descriptions
      ><template #footer
        ><n-space justify="end"
          ><n-button
            v-if="selected?.run_id"
            @click="router.push(`/runs/${selected.run_id}`)"
            >查看 Run</n-button
          ><n-button
            v-if="
              selected?.status === 'PENDING' && auth.can('approval:approve')
            "
            type="error"
            ghost
            @click="decide(selected!, 'reject')"
            >拒绝</n-button
          ><n-button
            v-if="
              selected?.status === 'PENDING' && auth.can('approval:approve')
            "
            type="primary"
            @click="decide(selected!, 'approve')"
            >批准</n-button
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
