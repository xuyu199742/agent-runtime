<script setup lang="ts">
import { h, ref } from "vue";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NForm,
  NFormItem,
  NInput,
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
  form = ref({ code: "", description: "" });
async function save() {
  saving.value = true;
  try {
    await api.post("/api/v1/admin/permissions", form.value);
    message.success("权限已保存");
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
    title: "权限码",
    key: "code",
    render: (row) =>
      h("span", { class: "mono", style: "font-size:11px" }, String(row.code)),
  },
  { title: "说明", key: "description" },
];
</script>
<template>
  <data-list
    ref="list"
    eyebrow="SYSTEM / PERMISSIONS"
    title="权限字典"
    description="管理服务端权限码。前端隐藏操作不代替服务端授权。"
    endpoint="/api/v1/admin/permissions"
    :columns="columns"
    ><template #top-actions
      ><n-button
        v-if="auth.can('role:update')"
        type="primary"
        @click="
          form = { code: '', description: '' };
          show = true;
        "
        >+ 新建权限</n-button
      ></template
    ></data-list
  ><n-drawer v-model:show="show" :width="500"
    ><n-drawer-content title="新增权限" closable
      ><n-form label-placement="top"
        ><n-form-item label="权限码"
          ><n-input
            v-model:value="form.code"
            placeholder="resource:action" /></n-form-item
        ><n-form-item label="说明"
          ><n-input v-model:value="form.description" /></n-form-item></n-form
      ><template #footer
        ><n-space justify="end"
          ><n-button @click="show = false">取消</n-button
          ><n-button type="primary" :loading="saving" @click="save"
            >保存</n-button
          ></n-space
        ></template
      ></n-drawer-content
    ></n-drawer
  >
</template>
