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
  useMessage,
} from "naive-ui";
import type { DataTableColumns } from "naive-ui";
import DataList from "../../components/DataList.vue";
import { api, type RecordData } from "../../api/client";
import { useAuthStore } from "../../stores/auth";

const auth = useAuthStore(),
  message = useMessage(),
  list = ref<InstanceType<typeof DataList> | null>(null),
  show = ref(false),
  saving = ref(false),
  currentId = ref<string | null>(null);
const permissions = ref<{ label: string; value: string }[]>([]),
  menus = ref<{ label: string; value: string }[]>([]);
const form = ref({
  name: "",
  description: "",
  permission_codes: [] as string[],
  menu_ids: [] as string[],
});
onMounted(async () => {
  try {
    const [p, m] = await Promise.all([
      api.get<RecordData[]>("/api/v1/admin/permissions"),
      api.get<RecordData[]>("/api/v1/admin/menus"),
    ]);
    permissions.value = p.map((item) => ({
      label: `${item.code} · ${item.description || ""}`,
      value: String(item.code),
    }));
    menus.value = m.map((item) => ({
      label: `${item.name} · ${item.path}`,
      value: String(item.id),
    }));
  } catch {
    /* 可在详情中查看已有角色 */
  }
});
function open(row?: RecordData) {
  currentId.value = row ? String(row.id) : null;
  form.value = {
    name: String(row?.name || ""),
    description: String(row?.description || ""),
    permission_codes: Array.isArray(row?.permission_codes)
      ? row.permission_codes.map(String)
      : [],
    menu_ids: Array.isArray(row?.menu_ids) ? row.menu_ids.map(String) : [],
  };
  show.value = true;
}
async function save() {
  saving.value = true;
  try {
    if (currentId.value)
      await api.put(`/api/v1/admin/roles/${currentId.value}`, form.value);
    else await api.post("/api/v1/admin/roles", form.value);
    message.success("角色已保存");
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
    title: "角色",
    key: "name",
    render: (row) => h("strong", { style: "font-size:12px" }, String(row.name)),
  },
  { title: "描述", key: "description" },
  {
    title: "权限数",
    key: "permission_codes",
    render: (row) =>
      String(
        Array.isArray(row.permission_codes) ? row.permission_codes.length : 0,
      ),
  },
  {
    title: "菜单数",
    key: "menu_ids",
    render: (row) =>
      String(Array.isArray(row.menu_ids) ? row.menu_ids.length : 0),
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
    eyebrow="SYSTEM / ROLES"
    title="角色管理"
    description="按角色分配服务端权限与导航菜单。"
    endpoint="/api/v1/admin/roles"
    :columns="columns"
    ><template #top-actions
      ><n-button v-if="auth.can('role:update')" type="primary" @click="open()"
        >+ 新建角色</n-button
      ></template
    ></data-list
  ><n-drawer v-model:show="show" :width="650"
    ><n-drawer-content :title="currentId ? '编辑角色' : '新建角色'" closable
      ><n-form label-placement="top"
        ><n-form-item label="角色名称"
          ><n-input v-model:value="form.name" /></n-form-item
        ><n-form-item label="描述"
          ><n-input
            v-model:value="form.description"
            type="textarea"
            :rows="2" /></n-form-item
        ><n-form-item label="权限"
          ><n-select
            v-model:value="form.permission_codes"
            :options="permissions"
            multiple
            filterable /></n-form-item
        ><n-form-item label="菜单"
          ><n-select
            v-model:value="form.menu_ids"
            :options="menus"
            multiple
            filterable /></n-form-item></n-form
      ><template #footer
        ><n-space justify="end"
          ><n-button @click="show = false">取消</n-button
          ><n-button
            v-if="auth.can('role:update')"
            type="primary"
            :loading="saving"
            @click="save"
            >保存角色</n-button
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
