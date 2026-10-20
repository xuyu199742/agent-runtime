<script setup lang="ts">
import { computed } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";

const props = defineProps<{ content: string }>();
const html = computed(() =>
  DOMPurify.sanitize(marked.parse(props.content, { async: false }) as string, {
    FORBID_TAGS: ["img", "iframe", "svg"],
  }),
);
</script>

<template>
  <div class="message-text markdown-text" v-html="html" />
</template>

<style scoped>
.markdown-text :deep(p) {
  margin: 0 0 0.7em;
}
.markdown-text :deep(p:last-child) {
  margin-bottom: 0;
}
.markdown-text :deep(pre) {
  overflow-x: auto;
  padding: 0.75em;
  border-radius: 8px;
  background: #f3f4f6;
}
.markdown-text :deep(a) {
  text-decoration: underline;
}
</style>
