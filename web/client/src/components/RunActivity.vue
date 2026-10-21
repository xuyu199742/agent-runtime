<script setup lang="ts">
import { computed } from "vue";
import type { Activity } from "../stream/agui";
import MarkdownText from "./MarkdownText.vue";
const props = defineProps<{
  items: Activity[];
  status?: string;
  answerText?: string;
}>();
const visible = computed(() =>
  props.items.filter((item) => ["model", "tool", "skill"].includes(item.type)),
);
const counts = computed(() => {
  const tools = visible.value.filter((item) => item.type === "tool").length;
  const skills = visible.value.filter((item) => item.type === "skill").length;
  return [
    tools ? `${tools} 次工具调用` : "",
    skills ? `${skills} 次 Skill 读取` : "",
  ]
    .filter(Boolean)
    .join(" · ");
});
function status(value: unknown): string {
  const key = String(value || "");
  return (
    (
      {
        RUNNING: "进行中",
        LOADING: "读取中",
        STARTED: "进行中",
        COMPLETED: "已完成",
        SUCCEEDED: "已完成",
        LOADED: "已读取",
        FAILED: "失败",
        ERROR: "失败",
        CANCELLED: "已停止",
        WAITING: "等待确认",
        PENDING: "等待执行",
      } as Record<string, string>
    )[key] || key
  );
}
function pretty(value: unknown): string {
  if (typeof value === "string") return value;
  return JSON.stringify(value, null, 2) ?? "";
}
</script>
<template>
  <details v-if="visible.length" class="run-activity">
    <summary>
      <span class="activity-mark">⌁</span> 执行过程
      <span class="activity-count">{{ counts }}</span
      ><span class="activity-chevron">⌄</span>
    </summary>
    <div class="activity-timeline">
      <div
        v-for="item in visible"
        :key="item.id"
        class="activity-step"
        :class="{
          failed: ['FAILED', 'ERROR'].includes(String(item.content.status)),
        }"
      >
        <template v-if="item.type === 'model'">
          <div class="activity-heading">
            <span>模型响应</span
            ><small>{{ status(item.content.status) }}</small>
          </div>
          <details
            v-if="item.content.reasoning"
            class="activity-detail reasoning-detail"
          >
            <summary>思考过程 <span class="activity-chevron">⌄</span></summary>
            <markdown-text :content="String(item.content.reasoning)" />
          </details>
          <span v-else class="activity-muted">尚未返回思考内容</span>
          <details
            v-if="
              item.content.text &&
              String(item.content.text).trim() !== (answerText || '').trim()
            "
            class="activity-detail model-output"
          >
            <summary>响应内容 <span class="activity-chevron">⌄</span></summary>
            <markdown-text :content="String(item.content.text)" />
          </details>
        </template>
        <details v-else-if="item.type === 'tool'" class="activity-detail">
          <summary>
            <span class="activity-kind">工具</span>
            {{ item.content.name || "工具调用" }}
            <small>{{ status(item.content.status) }}</small
            ><span class="activity-chevron">⌄</span>
          </summary>
          <template v-if="item.content.input !== undefined"
            ><label>输入</label>
            <pre>{{ pretty(item.content.input) }}</pre>
          </template>
          <template v-if="item.content.output !== undefined"
            ><label>输出</label>
            <pre>{{ pretty(item.content.output) }}</pre>
          </template>
          <p v-if="item.content.error" class="activity-error" role="status">
            {{ pretty(item.content.error) }}
          </p>
        </details>
        <details v-else class="activity-detail">
          <summary>
            <span class="activity-kind">Skill</span>
            {{ item.content.name || "Skill 读取" }}
            <small>{{ status(item.content.status) }}</small
            ><span class="activity-chevron">⌄</span>
          </summary>
          <dl class="skill-facts">
            <template v-if="item.content.resource"
              ><dt>实际读取资源</dt>
              <dd>{{ item.content.resource }}</dd></template
            >
            <template v-if="item.content.revision"
              ><dt>版本</dt>
              <dd>{{ item.content.revision }}</dd></template
            >
            <template v-if="item.content.contentHash"
              ><dt>内容哈希</dt>
              <dd>{{ item.content.contentHash }}</dd></template
            >
          </dl>
          <p v-if="item.content.error" class="activity-error">
            {{ pretty(item.content.error) }}
          </p>
        </details>
      </div>
    </div>
  </details>
</template>
