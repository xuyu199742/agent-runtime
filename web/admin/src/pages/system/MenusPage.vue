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
  NSpace,
  NSwitch,
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
const form = ref({
  name: "",
  path: "",
  parent_id: "",
  component: "",
  icon: "",
  permission_code: "",
  sort_order: 0,
  visible: true,
});
function open(row?: RecordData) {
  currentId.value = row ? String(row.id) : null;
  form.value = {
    name: String(row?.name || ""),
    path: String(row?.path || ""),
    parent_id: String(row?.parent_id || ""),
    component: String(row?.component || ""),
    icon: String(row?.icon || ""),
    permission_code: String(row?.permission_code || ""),
    sort_order: Number(row?.sort_order || 0),
    visible: row?.visible === undefined ? true : Boolean(row.visible),
  };
  show.value = true;
}
async function save() {
  saving.value = true;
  try {
    const body = {
      ...form.value,
      parent_id: form.value.parent_id || null,
      component: form.value.component || null,
      icon: form.value.icon || null,
      permission_code: form.value.permission_code || null,
    };
    if (currentId.value)
      await api.put(`/api/v1/admin/menus/${currentId.value}`, body);
    else await api.post("/api/v1/admin/menus", body);
    message.success("菜单已保存");
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
    title: "菜单名称",
    key: "name",
    render: (row) => h("strong", { style: "font-size:12px" }, String(row.name)),
  },
  { title: "路径", key: "path" },
  { title: "权限码", key: "permission_code" },
  { title: "排序", key: "sort_order" },
  {
    title: "可见",
    key: "visible",
    render: (row) => (row.visible ? "显示" : "隐藏"),
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
    eyebrow="SYSTEM / MENUS"
    title="菜单配置"
    description="维护服务端菜单数据与对应权限。控制台内置导航仍受权限约束。"
    endpoint="/api/v1/admin/menus"
    :columns="columns"
    ><template #top-actions
      ><n-button v-if="auth.can('menu:update')" type="primary" @click="open()"
        >+ 新建菜单</n-button
      ></template
    ></data-list
  ><n-drawer v-model:show="show" :width="560"
    ><n-drawer-content :title="currentId ? '编辑菜单' : '新建菜单'" closable
      ><n-form label-placement="top"
        ><n-form-item label="名称"
          ><n-input v-model:value="form.name" /></n-form-item
        ><n-form-item label="路径"
          ><n-input
            v-model:value="form.path"
            placeholder="/dashboard" /></n-form-item
        ><n-form-item label="父菜单 ID"
          ><n-input v-model:value="form.parent_id" /></n-form-item
        ><n-form-item label="组件"
          ><n-input v-model:value="form.component" /></n-form-item
        ><n-form-item label="图标"
          ><n-input v-model:value="form.icon" /></n-form-item
        ><n-form-item label="权限码"
          ><n-input v-model:value="form.permission_code" /></n-form-item
        ><n-form-item label="排序"
          ><n-input-number v-model:value="form.sort_order" /></n-form-item
        ><n-form-item label="可见"
          ><n-switch v-model:value="form.visible" /></n-form-item></n-form
      ><template #footer
        ><n-space justify="end"
          ><n-button @click="show = false">取消</n-button
          ><n-button
            v-if="auth.can('menu:update')"
            type="primary"
            :loading="saving"
            @click="save"
            >保存菜单</n-button
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
