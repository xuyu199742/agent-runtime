<script setup lang="ts">
import { onBeforeUnmount, ref, watch } from "vue";
import { NButton, NIcon, NSpin, useMessage } from "naive-ui";
import {
  CloseOutline,
  DownloadOutline,
  DocumentOutline,
} from "@vicons/ionicons5";
import { artifactBlob, downloadArtifact } from "../api/http";
import type { Artifact } from "../types/api";
import MarkdownText from "./MarkdownText.vue";

const props = defineProps<{
  show: boolean;
  artifacts: Artifact[];
  selectedId?: string | null;
}>();
const emit = defineEmits<{ "update:show": [value: boolean] }>();
const selected = ref<Artifact | null>(null),
  previewUrl = ref(""),
  previewText = ref(""),
  loading = ref(false),
  source = ref(false);
const message = useMessage();
let request = 0;
function clearPreview() {
  if (previewUrl.value) URL.revokeObjectURL(previewUrl.value);
  previewUrl.value = "";
  previewText.value = "";
}
async function select(item: Artifact) {
  const version = ++request;
  clearPreview();
  selected.value = item;
  source.value = false;
  loading.value = false;
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
    if (version !== request) return;
    if (
      item.mime_type.startsWith("text/") ||
      item.mime_type === "application/json"
    ) {
      const text = await blob.text();
      if (version === request) previewText.value = text;
    } else previewUrl.value = URL.createObjectURL(blob);
  } catch (cause) {
    if (version === request)
      message.error(cause instanceof Error ? cause.message : "预览失败");
  } finally {
    if (version === request) loading.value = false;
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
  () => [props.show, props.selectedId, props.artifacts] as const,
  ([open]) => {
    if (!open) {
      ++request;
      selected.value = null;
      clearPreview();
      return;
    }
    const item =
      props.artifacts.find((artifact) => artifact.id === props.selectedId) ||
      props.artifacts[0];
    if (item && item.id !== selected.value?.id) void select(item);
    if (!item) {
      ++request;
      selected.value = null;
      clearPreview();
    }
  },
  { immediate: true },
);
onBeforeUnmount(() => {
  ++request;
  clearPreview();
});
</script>
<template>
  <aside v-if="show" class="document-pane" aria-label="会话文件预览">
    <header class="document-header">
      <strong>{{ selected?.name || "会话文件" }}</strong
      ><button aria-label="关闭文件预览" @click="emit('update:show', false)">
        <n-icon :component="CloseOutline" />
      </button>
    </header>
    <div v-if="artifacts.length > 1" class="document-file-tabs">
      <button
        v-for="item in artifacts"
        :key="item.id"
        :class="{ active: selected?.id === item.id }"
        @click="select(item)"
      >
        {{ item.name }}
      </button>
    </div>
    <div v-if="selected" class="document-toolbar">
      <div class="document-modes" v-if="selected.mime_type.startsWith('text/')">
        <button
          :class="{ active: !source }"
          :aria-pressed="!source"
          @click="source = false"
        >
          阅读</button
        ><button
          :class="{ active: source }"
          :aria-pressed="source"
          @click="source = true"
        >
          源文
        </button>
      </div>
      <n-button size="tiny" quaternary @click="download(selected)"
        ><template #icon><n-icon :component="DownloadOutline" /></template
        >下载</n-button
      >
    </div>
    <div class="document-body">
      <n-spin :show="loading">
        <p v-if="!artifacts.length" class="document-empty">
          <n-icon :component="DocumentOutline" />这个会话还没有文件
        </p>
        <template v-else-if="selected">
          <img
            v-if="previewUrl && selected.mime_type.startsWith('image/')"
            :src="previewUrl"
            :alt="selected.name"
          />
          <iframe
            v-else-if="previewUrl && selected.mime_type === 'application/pdf'"
            :src="previewUrl"
            title="PDF 预览"
          />
          <markdown-text
            v-else-if="
              previewText &&
              !source &&
              (selected.mime_type.includes('markdown') ||
                /\.md$/i.test(selected.name))
            "
            :content="previewText"
          />
          <pre v-else-if="previewText">{{ previewText }}</pre>
          <p v-else-if="!loading" class="muted">
            此文件暂无可预览内容，可下载查看。
          </p>
        </template>
      </n-spin>
    </div>
  </aside>
</template>
