<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import {
  NButton,
  NDrawer,
  NDrawerContent,
  NEmpty,
  NSpin,
  useMessage,
} from "naive-ui";
import { DownloadOutline, DocumentOutline } from "@vicons/ionicons5";
import { artifactBlob, downloadArtifact } from "../api/http";
import type { Artifact } from "../types/api";

const props = defineProps<{ show: boolean; artifacts: Artifact[] }>();
const emit = defineEmits<{ "update:show": [value: boolean] }>();
const selected = ref<Artifact | null>(null),
  previewUrl = ref(""),
  previewText = ref(""),
  loading = ref(false);
const message = useMessage();
function clearPreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = "";
  previewText.value = "";
}
async function select(item: Artifact) {
  clearPreview();
  selected.value = item;
  if (
    !item.mime_type.startsWith("image/") &&
    item.mime_type !== "application/pdf" &&
    !item.mime_type.startsWith("text/") &&
    item.mime_type !== "application/json"
  )
    return;
  loading.value = true;
  try {
    const blob = await artifactBlob(item.id);
    if (selected.value?.id !== item.id) return;
    if (
      item.mime_type.startsWith("text/") ||
      item.mime_type === "application/json"
    )
      previewText.value = await blob.text();
    else previewUrl.value = URL.createObjectURL(blob);
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "预览失败");
  } finally {
    loading.value = false;
  }
}
async function download(item: Artifact) {
  try {
    await downloadArtifact(item.id, item.name);
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "下载失败");
  }
}
watch(
  () => props.show,
  (open) => {
    if (!open) {
      selected.value = null;
      clearPreview();
    }
  },
);
onBeforeUnmount(clearPreview);
</script>
<template>
  <n-drawer :show="show" :width="560" @update:show="emit('update:show', $event)"
    ><n-drawer-content title="会话文件" closable>
      <n-empty v-if="!artifacts.length" description="这个会话还没有文件" />
      <div v-else class="artifact-list">
        <button
          v-for="item in artifacts"
          :key="item.id"
          class="artifact-item"
          :class="{ active: selected?.id === item.id }"
          @click="select(item)"
        >
          <span class="artifact-icon"
            ><n-icon :component="DocumentOutline" /></span
          ><span class="artifact-info"
            ><strong>{{ item.name }}</strong
            ><small
              >{{ item.mime_type }} ·
              {{ Math.ceil(item.size / 1024) }} KB</small
            ></span
          >
        </button>
      </div>
      <div v-if="selected" class="artifact-preview">
        <div class="artifact-preview-head">
          <strong>{{ selected.name }}</strong
          ><n-button size="small" @click="download(selected)"
            ><template #icon><n-icon :component="DownloadOutline" /></template
            >下载</n-button
          >
        </div>
        <n-spin :show="loading"
          ><img
            v-if="previewUrl && selected.mime_type.startsWith('image/')"
            :src="previewUrl"
            :alt="selected.name"
          /><iframe
            v-else-if="previewUrl && selected.mime_type === 'application/pdf'"
            :src="previewUrl"
            title="PDF 预览"
          />
          <pre v-else-if="previewText">{{ previewText }}</pre>
          <p v-else-if="!loading" class="muted">
            此文件类型暂不支持在线预览，请下载查看。
          </p></n-spin
        >
      </div>
    </n-drawer-content></n-drawer
  >
</template>
