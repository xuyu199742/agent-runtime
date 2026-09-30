<script setup lang="ts">
import { h, ref } from "vue";
import {
  NAlert,
  NButton,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
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
import { api, type RecordData } from "../../api/client";
import { useAuthStore } from "../../stores/auth";

type Tool = RecordData & {
  id: string;
  name: string;
  description: string;
  type: string;
  config: RecordData;
  policy: RecordData;
  effect_type: string;
  failure_policy: string;
  enabled: boolean;
};
const auth = useAuthStore(),
  message = useMessage(),
  dialog = useDialog(),
  list = ref<InstanceType<typeof DataList> | null>(null);
const show = ref(false),
  saving = ref(false),
  testing = ref(false),
  currentId = ref<string | null>(null);
const form = ref({
  name: "calculator",
  description: "",
  type: "NATIVE",
  config: "{}",
  policy: "{}",
  failure_policy: "RETURN_ERROR",
  enabled: true,
});
const testArgs = ref('{"expression":"2+2"}'),
  testResult = ref("");
function open(row?: Tool) {
  currentId.value = row?.id || null;
  form.value = {
    name: row?.name || "calculator",
    description: row?.description || "",
    type: row?.type || "NATIVE",
    config: JSON.stringify(row?.config || {}, null, 2),
    policy: JSON.stringify(row?.policy || {}, null, 2),
    failure_policy: row?.failure_policy || "RETURN_ERROR",
    enabled: row?.enabled ?? true,
  };
  testResult.value = "";
  show.value = true;
}
function body() {
  return {
    name: form.value.name.trim(),
    description: form.value.description,
    type: form.value.type,
    config: JSON.parse(form.value.config),
    policy: JSON.parse(form.value.policy),
    effect_type: "READ_ONLY",
    failure_policy: form.value.failure_policy,
    enabled: form.value.enabled,
  };
}
async function save() {
  saving.value = true;
  try {
    const payload = body();
    if (currentId.value)
      await api.put(`/api/v1/admin/tools/${currentId.value}`, payload);
    else await api.post("/api/v1/admin/tools", payload);
    message.success("工具已保存");
    show.value = false;
    list.value?.reload();
  } catch (error) {
    message.error(
      error instanceof SyntaxError
        ? "Config / Policy 必须是有效 JSON"
        : error instanceof Error
          ? error.message
          : "保存失败",
    );
  } finally {
    saving.value = false;
  }
}
async function test(row?: Tool) {
  const id = row?.id || currentId.value;
  if (!id) {
    message.warning("请先保存 Tool");
    return;
  }
  testing.value = true;
  try {
    const result = await api.post<RecordData>(
      `/api/v1/admin/tools/${id}/test`,
      { args: JSON.parse(testArgs.value) },
    );
    testResult.value = JSON.stringify(result, null, 2);
    result.success
      ? message.success("工具测试通过")
      : message.error(String(result.message || "工具测试失败"));
  } catch (error) {
    message.error(
      error instanceof SyntaxError
        ? "测试参数必须是有效 JSON"
        : error instanceof Error
          ? error.message
          : "工具测试失败",
    );
  } finally {
    testing.value = false;
  }
}
async function actionNow(row: Tool, operation: string) {
  try {
    await api.post(`/api/v1/admin/tools/${row.id}/${operation}`);
    message.success("状态已更新");
    list.value?.reload();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "操作失败");
  }
}
function archive(row: Tool) {
  dialog.warning({
    title: "归档工具",
    content: `确定归档「${row.name}」？`,
    positiveText: "归档",
    negativeText: "取消",
    onPositiveClick: () => actionNow(row, "archive"),
  });
}
const columns: DataTableColumns<RecordData> = [
  {
    title: "工具",
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
    title: "类型",
    key: "type",
    render: (row) =>
      h(
        NTag,
        { size: "small", bordered: false },
        { default: () => String(row.type) },
      ),
  },
  { title: "副作用", key: "effect_type" },
  { title: "失败策略", key: "failure_policy" },
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
                onClick: () => open(row as Tool),
              },
              { default: () => "查看 / 编辑" },
            ),
            auth.can("tool:test")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    onClick: () => {
                      open(row as Tool);
                      test(row as Tool);
                    },
                  },
                  { default: () => "测试" },
                )
              : null,
            auth.can("tool:update")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    onClick: () =>
                      actionNow(
                        row as Tool,
                        row.enabled ? "disable" : "enable",
                      ),
                  },
                  { default: () => (row.enabled ? "停用" : "启用") },
                )
              : null,
            auth.can("tool:update")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    type: "error",
                    onClick: () => archive(row as Tool),
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
    eyebrow="CONFIGURATION / TOOLS"
    title="工具注册"
    description="工具实现由代码提供；这里管理启用状态、描述、配置与执行策略。"
    endpoint="/api/v1/admin/tools"
    :columns="columns"
    searchable
    ><template #top-actions
      ><n-button v-if="auth.can('tool:update')" type="primary" @click="open()"
        >+ 新建工具</n-button
      ></template
    ></data-list
  >
  <n-drawer v-model:show="show" :width="610"
    ><n-drawer-content :title="currentId ? '编辑工具' : '新建工具'" closable
      ><n-alert type="info" style="margin-bottom: 18px"
        >V0.2 仅支持 READ_ONLY
        工具。需要副作用的工具必须先具备幂等实现。</n-alert
      ><n-form label-placement="top"
        ><n-form-item label="实现名称"
          ><n-select
            v-model:value="form.name"
            :options="[
              { label: 'calculator', value: 'calculator' },
              { label: 'echo', value: 'echo' },
              { label: 'http_request', value: 'http_request' },
            ]" /></n-form-item
        ><n-form-item label="类型"
          ><n-select
            v-model:value="form.type"
            :options="[
              { label: 'NATIVE', value: 'NATIVE' },
              { label: 'HTTP', value: 'HTTP' },
            ]" /></n-form-item
        ><n-form-item label="描述"
          ><n-input
            v-model:value="form.description"
            type="textarea"
            :rows="2" /></n-form-item
        ><n-form-item label="Config · JSON"
          ><n-input
            v-model:value="form.config"
            type="textarea"
            :rows="4"
            class="mono" /></n-form-item
        ><n-form-item label="Policy · JSON"
          ><n-input
            v-model:value="form.policy"
            type="textarea"
            :rows="4"
            class="mono" /></n-form-item
        ><n-form-item label="失败策略"
          ><n-select
            v-model:value="form.failure_policy"
            :options="[
              { label: '返回错误给 Agent', value: 'RETURN_ERROR' },
              { label: '终止 Run', value: 'FAIL_RUN' },
            ]" /></n-form-item
        ><n-form-item label="启用"
          ><n-switch v-model:value="form.enabled" /></n-form-item
        ><template v-if="currentId"
          ><div class="detail-section">
            <h3>运行测试</h3>
            <n-input
              v-model:value="testArgs"
              type="textarea"
              :rows="3"
              class="mono"
            /><n-button
              style="margin-top: 10px"
              :loading="testing"
              @click="test()"
              >执行测试</n-button
            >
            <pre v-if="testResult" class="code-box">{{ testResult }}</pre>
          </div></template
        ></n-form
      ><template #footer
        ><n-space justify="end"
          ><n-button @click="show = false">取消</n-button
          ><n-button
            v-if="auth.can('tool:update')"
            type="primary"
            :loading="saving"
            @click="save"
            >保存工具</n-button
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
