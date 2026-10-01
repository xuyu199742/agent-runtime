<script setup lang="ts">
import { h, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NModal,
  NSelect,
  NSpace,
  NSwitch,
  NTag,
  useDialog,
  useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import StatusLabel from "../../components/StatusLabel.vue";
import { api, type Page, type RecordData } from "../../api/client";
import { useAuthStore } from "../../stores/auth";

type Agent = RecordData & {
  id: string;
  name: string;
  description: string;
  system_prompt: string;
  model_id: string;
  tool_ids: string[];
  max_model_calls: number;
  revision: number;
  enabled: boolean;
};
const auth = useAuthStore(),
  message = useMessage(),
  dialog = useDialog(),
  router = useRouter(),
  list = ref<InstanceType<typeof DataList> | null>(null);
const show = ref(false),
  saving = ref(false),
  currentId = ref<string | null>(null),
  revisions = ref<RecordData[]>([]);
const models = ref<{ label: string; value: string }[]>([]),
  tools = ref<{ label: string; value: string }[]>([]);
const loadingModels = ref(false),
  loadingTools = ref(false);
const form = ref({
  name: "",
  description: "",
  system_prompt: "",
  model_id: "",
  tool_ids: [] as string[],
  max_model_calls: 10,
  enabled: true,
});
const testDialog = ref(false),
  testContent = ref(""),
  testAgent = ref<Agent | null>(null),
  testing = ref(false);
async function searchModels(keyword = "") {
  loadingModels.value = true;
  try {
    const page = await api.get<Page<RecordData>>(
      `/api/v1/admin/models?page_size=100&enabled=true&keyword=${encodeURIComponent(keyword)}`,
    );
    const selected = models.value.find(
      (option) => option.value === form.value.model_id,
    );
    models.value = [
      ...(selected ? [selected] : []),
      ...page.items
        .filter((item) => item.id !== selected?.value)
        .map((item) => ({ label: String(item.name), value: String(item.id) })),
    ];
  } catch {
    /* 无模型查看权限时保持表单可读 */
  } finally {
    loadingModels.value = false;
  }
}
async function searchTools(keyword = "") {
  loadingTools.value = true;
  try {
    const page = await api.get<Page<RecordData>>(
      `/api/v1/admin/tools?page_size=100&enabled=true&keyword=${encodeURIComponent(keyword)}`,
    );
    const selected = tools.value.filter((option) =>
      form.value.tool_ids.includes(option.value),
    );
    tools.value = [
      ...selected,
      ...page.items
        .filter((item) => !selected.some((option) => option.value === item.id))
        .map((item) => ({ label: String(item.name), value: String(item.id) })),
    ];
  } catch {
    /* 无工具查看权限时保持表单可读 */
  } finally {
    loadingTools.value = false;
  }
}
onMounted(() => {
  searchModels();
  searchTools();
});
async function keepSelectedOptions(row: Agent) {
  if (
    row.model_id &&
    !models.value.some((option) => option.value === row.model_id)
  ) {
    try {
      const model = await api.get<RecordData>(
        `/api/v1/admin/models/${row.model_id}`,
      );
      models.value.unshift({ label: String(model.name), value: row.model_id });
    } catch {
      /* 已删除的历史模型仍按 ID 展示 */
    }
  }
  for (const id of row.tool_ids || []) {
    if (tools.value.some((option) => option.value === id)) continue;
    try {
      const tool = await api.get<RecordData>(`/api/v1/admin/tools/${id}`);
      tools.value.push({ label: String(tool.name), value: id });
    } catch {
      /* 已删除的历史工具仍按 ID 展示 */
    }
  }
}
async function open(row?: Agent, clone = false) {
  currentId.value = clone ? null : row?.id || null;
  form.value = {
    name: clone ? `${row?.name || ""} 副本` : row?.name || "",
    description: row?.description || "",
    system_prompt: row?.system_prompt || "",
    model_id: row?.model_id || "",
    tool_ids: row?.tool_ids || [],
    max_model_calls: row?.max_model_calls || 10,
    enabled: row?.enabled ?? true,
  };
  revisions.value = [];
  show.value = true;
  if (row) await keepSelectedOptions(row);
  if (currentId.value) {
    try {
      revisions.value = await api.get<RecordData[]>(
        `/api/v1/admin/agents/${currentId.value}/revisions`,
      );
    } catch {
      /* 详情仍可编辑 */
    }
  }
}
async function save() {
  saving.value = true;
  try {
    if (currentId.value)
      await api.put(`/api/v1/admin/agents/${currentId.value}`, form.value);
    else await api.post("/api/v1/admin/agents", form.value);
    message.success("Agent 已保存");
    show.value = false;
    list.value?.reload();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "保存失败");
  } finally {
    saving.value = false;
  }
}
function test(row: Agent) {
  testAgent.value = row;
  testContent.value = "";
  testDialog.value = true;
}
async function runTest() {
  if (!testAgent.value || !testContent.value.trim()) {
    message.warning("请输入测试消息");
    return;
  }
  testing.value = true;
  try {
    const result = await api.post<{ run_id: string }>(
      `/api/v1/admin/agents/${testAgent.value.id}/test`,
      { content: testContent.value.trim() },
    );
    testDialog.value = false;
    router.push(`/runs/${result.run_id}`);
  } catch (error) {
    message.error(error instanceof Error ? error.message : "测试失败");
  } finally {
    testing.value = false;
  }
}
async function actionNow(row: Agent, operation: string) {
  try {
    await api.post(`/api/v1/admin/agents/${row.id}/${operation}`);
    message.success("状态已更新");
    list.value?.reload();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "操作失败");
  }
}
function archive(row: Agent) {
  dialog.warning({
    title: "归档 Agent",
    content: `确定归档「${row.name}」？`,
    positiveText: "归档",
    negativeText: "取消",
    onPositiveClick: () => actionNow(row, "archive"),
  });
}
const columns: DataTableColumns<RecordData> = [
  {
    title: "Agent",
    key: "name",
    render: (row) =>
      h("div", [
        h("strong", { style: "font-size:12px" }, String(row.name)),
        h(
          "div",
          { class: "muted", style: "font-size:10px" },
          String(row.description || "暂无描述"),
        ),
      ]),
  },
  {
    title: "Model",
    key: "model_id",
    render: (row) =>
      models.value.find((m) => m.value === row.model_id)?.label ||
      String(row.model_id).slice(0, 10),
  },
  {
    title: "工具",
    key: "tool_ids",
    render: (row) =>
      `${Array.isArray(row.tool_ids) ? row.tool_ids.length : 0} tools`,
  },
  {
    title: "Revision",
    key: "revision",
    render: (row) =>
      h(
        NTag,
        { size: "small", bordered: false },
        { default: () => `R${row.revision}` },
      ),
  },
  {
    title: "状态",
    key: "enabled",
    render: (row) => h(StatusLabel, { value: Boolean(row.enabled) }),
  },
  {
    title: "操作",
    key: "actions",
    render: (row) =>
      h(
        NSpace,
        { size: 4 },
        {
          default: () => [
            h(
              NButton,
              {
                size: "tiny",
                quaternary: true,
                onClick: () => open(row as Agent),
              },
              { default: () => "详情 / 编辑" },
            ),
            auth.can("agent:test")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    onClick: () => test(row as Agent),
                  },
                  { default: () => "测试" },
                )
              : null,
            auth.can("agent:update")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    onClick: () => open(row as Agent, true),
                  },
                  { default: () => "克隆" },
                )
              : null,
            auth.can("agent:update")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    onClick: () =>
                      actionNow(
                        row as Agent,
                        row.enabled ? "disable" : "enable",
                      ),
                  },
                  { default: () => (row.enabled ? "停用" : "启用") },
                )
              : null,
            auth.can("agent:update")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    type: "error",
                    onClick: () => archive(row as Agent),
                  },
                  { default: () => "归档" },
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
    eyebrow="CONFIGURATION / AGENTS"
    title="Agent 管理"
    description="管理 Agent 指令、模型、工具与版本。运行时使用创建 Run 时的配置快照。"
    endpoint="/api/v1/admin/agents"
    :columns="columns"
    searchable
    ><template #top-actions
      ><n-button v-if="auth.can('agent:update')" type="primary" @click="open()"
        >+ 新建 Agent</n-button
      ></template
    ></data-list
  >
  <n-drawer v-model:show="show" :width="650"
    ><n-drawer-content
      :title="currentId ? 'Agent 详情 / 编辑' : '新建 Agent'"
      closable
      ><n-form label-placement="top"
        ><n-form-item label="名称"
          ><n-input v-model:value="form.name" /></n-form-item
        ><n-form-item label="描述"
          ><n-input
            v-model:value="form.description"
            type="textarea"
            :rows="2" /></n-form-item
        ><n-form-item label="System Prompt"
          ><n-input
            v-model:value="form.system_prompt"
            type="textarea"
            :rows="7"
            class="mono"
            placeholder="Agent 的系统指令" /></n-form-item
        ><n-form-item label="模型"
          ><n-select
            v-model:value="form.model_id"
            :options="models"
            :loading="loadingModels"
            filterable
            remote
            placeholder="搜索并选择模型"
            @search="searchModels" /></n-form-item
        ><n-form-item label="工具"
          ><n-select
            v-model:value="form.tool_ids"
            :options="tools"
            :loading="loadingTools"
            multiple
            filterable
            remote
            placeholder="搜索并选择工具"
            @search="searchTools" /></n-form-item
        ><n-form-item label="最大模型调用次数"
          ><n-input-number
            v-model:value="form.max_model_calls"
            :min="1"
            :max="100" /></n-form-item
        ><n-form-item label="启用"
          ><n-switch v-model:value="form.enabled" /></n-form-item
      ></n-form>
      <div v-if="revisions.length" class="detail-section">
        <h3>历史版本</h3>
        <div
          v-for="revision in revisions"
          :key="String(revision.id)"
          class="revision-row"
        >
          <span class="mono">R{{ revision.revision }}</span
          ><span class="muted">{{
            new Date(String(revision.created_at)).toLocaleString("zh-CN")
          }}</span>
        </div>
      </div>
      <template #footer
        ><n-space justify="end"
          ><n-button @click="show = false">关闭</n-button
          ><n-button
            v-if="auth.can('agent:update')"
            type="primary"
            :loading="saving"
            @click="save"
            >保存 Agent</n-button
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
  <n-modal
    v-model:show="testDialog"
    preset="card"
    :title="`测试 ${testAgent?.name || 'Agent'}`"
    style="width: min(520px, 90vw)"
    ><p class="muted" style="font-size: 12px">
      测试会创建独立 Conversation 和 Run，可在运行详情中查看结果。
    </p>
    <n-input
      v-model:value="testContent"
      type="textarea"
      :rows="5"
      placeholder="输入一条测试消息"
    /><template #footer
      ><n-space justify="end"
        ><n-button @click="testDialog = false">取消</n-button
        ><n-button type="primary" :loading="testing" @click="runTest"
          >开始测试</n-button
        ></n-space
      ></template
    ></n-modal
  >
</template>
<style scoped>
.revision-row {
  display: flex;
  justify-content: space-between;
  border-bottom: 1px solid var(--border);
  padding: 11px 0;
  font-size: 11px;
}
</style>
