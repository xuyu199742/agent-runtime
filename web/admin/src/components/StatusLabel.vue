<script setup lang="ts">
import { computed } from "vue";
const props = defineProps<{ value: string | boolean | null | undefined }>();
const label = computed(() =>
  props.value === true
    ? "启用"
    : props.value === false
      ? "停用"
      : String(props.value || "—"),
);
const tone = computed(() =>
  ["COMPLETED", "APPROVED", "ACTIVE", "启用"].includes(label.value)
    ? "success"
    : ["FAILED", "REJECTED", "CANCELLED", "停用"].includes(label.value)
      ? "error"
      : ["WAITING", "PENDING"].includes(label.value)
        ? "warning"
        : "info",
);
</script>
<template>
  <span class="status-label"
    ><i class="status-dot" :class="tone" />{{ label }}</span
  >
</template>
<style scoped>
.status-label {
  display: inline-flex;
  align-items: center;
  white-space: nowrap;
  font-family: "IBM Plex Mono", monospace;
  font-size: 10px;
  font-weight: 500;
}
.status-dot {
  margin-right: 6px;
}
</style>
