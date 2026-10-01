<script setup lang="ts">
import {
  NDrawer,
  NDrawerContent,
  NDescriptions,
  NDescriptionsItem,
} from "naive-ui";
import type { RecordData } from "../api/client";

const open = defineModel<boolean>("open", { default: false });
const props = defineProps<{
  title: string;
  row: RecordData | null;
  fields: {
    label: string;
    key: string;
    format?: (value: unknown, row: RecordData) => string;
  }[];
}>();
function value(
  key: string,
  format?: (value: unknown, row: RecordData) => string,
) {
  if (!props.row) return "—";
  const raw = props.row[key];
  if (format) return format(raw, props.row);
  if (raw === null || raw === undefined || raw === "") return "—";
  if (typeof raw === "object") return JSON.stringify(raw, null, 2);
  return String(raw);
}
</script>

<template>
  <n-drawer v-model:show="open" :width="620" placement="right"
    ><n-drawer-content :title="title" closable
      ><n-descriptions label-placement="left" :column="1" bordered
        ><n-descriptions-item
          v-for="field in fields"
          :key="field.key"
          :label="field.label"
          ><span style="white-space: pre-wrap; word-break: break-word">{{
            value(field.key, field.format)
          }}</span></n-descriptions-item
        ></n-descriptions
      ><slot /></n-drawer-content
  ></n-drawer>
</template>
