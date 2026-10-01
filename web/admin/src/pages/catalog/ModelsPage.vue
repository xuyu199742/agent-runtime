<script setup lang="ts">
import { h, ref } from "vue";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
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

type Model = RecordData & {
  id: string;
  name: string;
  provider: string;
  model_name: string;
  base_url?: string;
  config: Record<string, number>;
  enabled: boolean;
  has_api_key: boolean;
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
  name: "",
  provider: "openai-compatible",
  model_name: "",
  base_url: "",
  api_key: "",
  timeout_seconds: 60,
  max_retries: 1,
  temperature: 0.7,
  enabled: true,
});
function open(row?: Model) {
  currentId.value = row?.id || null;
  form.value = {
    name: row?.name || "",
    provider: row?.provider || "openai-compatible",
    model_name: row?.model_name || "",
    base_url: row?.base_url || "",
    api_key: "",
    timeout_seconds: row?.config?.timeout_seconds ?? 60,
    max_retries: row?.config?.max_retries ?? 1,
    temperature: row?.config?.temperature ?? 0.7,
    enabled: row?.enabled ?? true,
  };
  show.value = true;
}
function body() {
  return {
    name: form.value.name.trim(),
    provider: form.value.provider,
    model_name: form.value.model_name.trim(),
    base_url: form.value.base_url.trim() || null,
    api_key: form.value.api_key || null,
    config: {
      timeout_seconds: form.value.timeout_seconds,
      max_retries: form.value.max_retries,
      temperature: form.value.temperature,
    },
    enabled: form.value.enabled,
  };
}
async function save() {
  saving.value = true;
  try {
    if (currentId.value)
      await api.put(`/api/v1/admin/models/${currentId.value}`, body());
    else await api.post("/api/v1/admin/models", body());
    message.success("模型已保存");
    show.value = false;
    list.value?.reload();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "保存失败");
  } finally {
    saving.value = false;
  }
}
async function test(row?: Model) {
  testing.value = true;
  try {
    const result = row
      ? await api.post<RecordData>(
          `/api/v1/admin/models/${row.id}/test-connection`,
        )
      : await api.post<RecordData>(
          "/api/v1/admin/models/test-connection",
          body(),
        );
    if (result.success)
      message.success(`连接成功 · ${result.latency_ms ?? "—"} ms`);
    else
      message.error(`连接失败 · ${result.stage || result.code || "未知阶段"}`);
  } catch (error) {
    message.error(error instanceof Error ? error.message : "连接测试失败");
  } finally {
    testing.value = false;
  }
}
async function action(row: Model, operation: "enable" | "disable" | "archive") {
  if (operation === "archive") {
    dialog.warning({
      title: "归档模型",
      content: `确定归档「${row.name}」？归档后不会出现在可选列表。`,
      positiveText: "归档",
      negativeText: "取消",
      onPositiveClick: () => actionNow(row, operation),
    });
    return;
  }
  await actionNow(row, operation);
}
async function actionNow(row: Model, operation: string) {
  try {
    await api.post(`/api/v1/admin/models/${row.id}/${operation}`);
    message.success("状态已更新");
    list.value?.reload();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "操作失败");
  }
}
const columns: DataTableColumns<RecordData> = [
  {
    title: "模型名称",
    key: "name",
    render: (row) =>
      h("div", [
        h("strong", { style: "font-size:12px" }, String(row.name)),
        h("div", { class: "mini-id" }, String(row.id).slice(0, 18)),
      ]),
  },
  {
    title: "Provider",
    key: "provider",
    render: (row) =>
      h(
        NTag,
        { size: "small", bordered: false },
        { default: () => String(row.provider) },
      ),
  },
  { title: "模型", key: "model_name" },
  { title: "Base URL", key: "base_url", ellipsis: { tooltip: true } },
  {
    title: "密钥",
    key: "has_api_key",
    render: (row) => (row.has_api_key ? "••••••••" : "未配置"),
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
                onClick: () => open(row as Model),
              },
              { default: () => "查看 / 编辑" },
            ),
            auth.can("model:test")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    onClick: () => test(row as Model),
                  },
                  { default: () => "连接测试" },
                )
              : null,
            auth.can("model:update")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    onClick: () =>
                      action(row as Model, row.enabled ? "disable" : "enable"),
                  },
                  { default: () => (row.enabled ? "停用" : "启用") },
                )
              : null,
            auth.can("model:update")
              ? h(
                  NButton,
                  {
                    size: "tiny",
                    quaternary: true,
                    type: "error",
                    onClick: () => action(row as Model, "archive"),
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
    eyebrow="CONFIGURATION / MODELS"
    title="模型配置"
    description="管理模型连接与凭证，密钥保存后只显示配置状态。"
    endpoint="/api/v1/admin/models"
    :columns="columns"
    searchable
    ><template #top-actions
      ><n-button v-if="auth.can('model:update')" type="primary" @click="open()"
        >+ 新建模型</n-button
      ></template
    ></data-list
  >
  <n-drawer v-model:show="show" :width="560"
    ><n-drawer-content :title="currentId ? '编辑模型' : '新建模型'" closable
      ><n-form label-placement="top" autocomplete="off"
        ><n-form-item label="名称"
          ><n-input
            v-model:value="form.name"
            placeholder="例如：生产环境 GPT"
            :input-props="{ autocomplete: 'off' }" /></n-form-item
        ><n-form-item label="Provider"
          ><n-select
            v-model:value="form.provider"
            :options="[
              { label: 'OpenAI Compatible', value: 'openai-compatible' },
              { label: 'OpenAI', value: 'openai' },
            ]" /></n-form-item
        ><n-form-item label="Model Name"
          ><n-input
            v-model:value="form.model_name"
            placeholder="模型标识"
            :input-props="{ autocomplete: 'off' }" /></n-form-item
        ><n-form-item label="Base URL"
          ><n-input
            v-model:value="form.base_url"
            placeholder="https://.../v1"
            :input-props="{ autocomplete: 'off' }" /></n-form-item
        ><n-form-item :label="currentId ? 'API Key（留空保持原值）' : 'API Key'"
          ><n-input
            v-model:value="form.api_key"
            type="password"
            show-password-on="click"
            placeholder="输入密钥，不会回显"
            :input-props="{ autocomplete: 'new-password' }"
        /></n-form-item>
        <div class="detail-grid">
          <n-form-item label="超时（秒）"
            ><n-input-number
              v-model:value="form.timeout_seconds"
              :min="1"
              :max="300" /></n-form-item
          ><n-form-item label="重试次数"
            ><n-input-number
              v-model:value="form.max_retries"
              :min="0"
              :max="5" /></n-form-item
          ><n-form-item label="Temperature"
            ><n-input-number
              v-model:value="form.temperature"
              :min="0"
              :max="2"
              :step="0.1"
          /></n-form-item>
        </div>
        <n-form-item label="启用"
          ><n-switch v-model:value="form.enabled" /></n-form-item></n-form
      ><template #footer
        ><n-space justify="space-between"
          ><n-button
            v-if="auth.can('model:test')"
            :loading="testing"
            @click="test()"
            >测试当前配置</n-button
          ><n-space
            ><n-button @click="show = false">取消</n-button
            ><n-button
              v-if="auth.can('model:update')"
              type="primary"
              :loading="saving"
              @click="save"
              >保存模型</n-button
            ></n-space
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
