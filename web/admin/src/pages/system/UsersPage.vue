<script setup lang="ts">
import { h, onMounted, ref } from "vue";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
  NSelect,
  NSpace,
  NSwitch,
  useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import StatusLabel from "../../components/StatusLabel.vue";
import { api, type RecordData } from "../../api/client";
import { useAuthStore } from "../../stores/auth";

const auth = useAuthStore(),
  message = useMessage(),
  list = ref<InstanceType<typeof DataList> | null>(null),
  show = ref(false),
  saving = ref(false),
  currentId = ref<string | null>(null);
const roles = ref<{ label: string; value: string }[]>([]);
const form = ref({
  username: "",
  display_name: "",
  password: "",
  enabled: true,
  role_ids: [] as string[],
});
onMounted(async () => {
  try {
    roles.value = (await api.get<RecordData[]>("/api/v1/admin/roles")).map(
      (row) => ({ label: String(row.name), value: String(row.id) }),
    );
  } catch {
    /* 缺少角色查看权限时不展示可选角色 */
  }
});
function open(row?: RecordData) {
  currentId.value = row ? String(row.id) : null;
  form.value = {
    username: String(row?.username || ""),
    display_name: String(row?.display_name || ""),
    password: "",
    enabled: row?.enabled === undefined ? true : Boolean(row.enabled),
    role_ids: Array.isArray(row?.role_ids) ? row.role_ids.map(String) : [],
  };
  show.value = true;
}
async function save() {
  saving.value = true;
  try {
    const body = { ...form.value, password: form.value.password || null };
    if (currentId.value)
      await api.put(`/api/v1/admin/users/${currentId.value}`, body);
    else await api.post("/api/v1/admin/users", body);
    message.success("用户已保存");
    show.value = false;
    list.value?.reload();
  } catch (error) {
    message.error(error instanceof Error ? error.message : "保存失败");
  } finally {
    saving.value = false;
  }
}
const columns: DataTableColumns<RecordData> = [
  {
    title: "用户名",
    key: "username",
    render: (row) =>
      h("strong", { style: "font-size:12px" }, String(row.username)),
  },
  { title: "显示名称", key: "display_name" },
  {
    title: "角色数量",
    key: "role_ids",
    render: (row) =>
      String(Array.isArray(row.role_ids) ? row.role_ids.length : 0),
  },
  {
    title: "状态",
    key: "enabled",
    render: (row) => h(StatusLabel, { value: Boolean(row.enabled) }),
  },
  {
    title: "创建时间",
    key: "created_at",
    render: (row) => new Date(String(row.created_at)).toLocaleString("zh-CN"),
  },
  {
    title: "操作",
    key: "action",
    render: (row) =>
      h(
        NButton,
        { size: "tiny", quaternary: true, onClick: () => open(row) },
        { default: () => "查看 / 编辑" },
      ),
  },
];
</script>
<template>
  <data-list
    ref="list"
    eyebrow="SYSTEM / USERS"
    title="用户管理"
    description="管理控制台和客户端账号、状态及角色归属。"
    endpoint="/api/v1/admin/users"
    :columns="columns"
    searchable
    ><template #top-actions
      ><n-button v-if="auth.can('user:update')" type="primary" @click="open()"
        >+ 新建用户</n-button
      ></template
    ></data-list
  ><n-drawer v-model:show="show" :width="560"
    ><n-drawer-content :title="currentId ? '编辑用户' : '新建用户'" closable
      ><n-form label-placement="top"
        ><n-form-item label="用户名"
          ><n-input v-model:value="form.username" /></n-form-item
        ><n-form-item label="显示名称"
          ><n-input v-model:value="form.display_name" /></n-form-item
        ><n-form-item
          :label="currentId ? '密码（留空保持原值）' : '密码（至少 12 位）'"
          ><n-input
            v-model:value="form.password"
            type="password"
            show-password-on="click" /></n-form-item
        ><n-form-item label="角色"
          ><n-select
            v-model:value="form.role_ids"
            :options="roles"
            multiple
            filterable /></n-form-item
        ><n-form-item label="启用"
          ><n-switch v-model:value="form.enabled" /></n-form-item></n-form
      ><template #footer
        ><n-space justify="end"
          ><n-button @click="show = false">取消</n-button
          ><n-button
            v-if="auth.can('user:update')"
            type="primary"
            :loading="saving"
            @click="save"
            >保存用户</n-button
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
