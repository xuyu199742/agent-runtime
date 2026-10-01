<script setup lang="ts">
import { computed, nextTick, onMounted, ref, watch } from "vue";
import { useRoute, useRouter } from "vue-router";
import {
  NButton,
  NIcon,
  NInput,
  NModal,
  NSpin,
  useDialog,
  useMessage,
} from "naive-ui";
import {
  AddOutline,
  ArrowUpOutline,
  AttachOutline,
  ChevronDownOutline,
  CloseOutline,
  CreateOutline,
  EllipsisHorizontalOutline,
  LogOutOutline,
  MenuOutline,
  PaperPlaneOutline,
  PersonOutline,
  RefreshOutline,
  SearchOutline,
  SparklesOutline,
  StopOutline,
  TrashOutline,
} from "@vicons/ionicons5";
import { useAuthStore } from "../stores/auth";
import { useChat } from "../composables/useChat";
import { isTerminal } from "../stream/state";
import ArtifactViewer from "../components/ArtifactViewer.vue";

const auth = useAuthStore(),
  route = useRoute(),
  router = useRouter(),
  message = useMessage(),
  dialog = useDialog();
const {
  agents,
  conversations,
  hasMoreConversations,
  current,
  messages,
  hasOlderMessages,
  run,
  stream,
  approvals,
  artifacts,
  loading,
  sending,
  reconnecting,
  error,
  loadAgents,
  loadConversations,
  loadOlderMessages,
  openConversation,
  createConversation,
  send,
  stop,
  decideApproval,
  rename,
  archive,
  clearCurrent,
  connectRun,
} = useChat();
const draft = ref(""),
  search = ref(""),
  agentSearch = ref(""),
  selectedAgentId = ref(""),
  sidebarOpen = ref(false),
  profileOpen = ref(false),
  artifactsOpen = ref(false),
  renameOpen = ref(false),
  renameDraft = ref("");
const composer = ref<HTMLTextAreaElement | null>(null),
  scroller = ref<HTMLElement | null>(null);
const visibleConversations = computed(() =>
  conversations.value.filter((item) =>
    `${item.title} ${item.agent.name}`
      .toLowerCase()
      .includes(search.value.toLowerCase()),
  ),
);
const visibleAgents = computed(() => {
  const keyword = agentSearch.value.trim().toLowerCase();
  const found = agents.value.filter((item) =>
    `${item.name} ${item.description}`.toLowerCase().includes(keyword),
  );
  if (keyword) return found.slice(0, 12);
  const selected = found.find((item) => item.id === selectedAgentId.value);
  return [
    selected,
    ...found.filter((item) => item.id !== selectedAgentId.value),
  ]
    .filter((item): item is (typeof found)[number] => !!item)
    .slice(0, 6);
});
const currentAgent = computed(() =>
  agents.value.find(
    (item) => item.id === (current.value?.agent.id || selectedAgentId.value),
  ),
);
const busy = computed(() => !!run.value && !isTerminal(run.value.status));
const lastUserContent = computed(
  () =>
    [...messages.value]
      .reverse()
      .find((item) => ["user", "human"].includes(item.role.toLowerCase()))
      ?.content || "",
);
const pendingApprovals = computed(() =>
  approvals.value.filter((item) => item.status === "PENDING"),
);
const statusText = computed(
  () =>
    ({
      PENDING: "排队中",
      RUNNING: "正在思考",
      WAITING: "等待确认",
      COMPLETED: "已完成",
      FAILED: "执行失败",
      CANCELLED: "已停止",
    })[stream.value.status] || stream.value.status,
);

onMounted(async () => {
  try {
    await Promise.all([loadAgents(), loadConversations()]);
    selectedAgentId.value ||= agents.value[0]?.id || "";
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "初始化失败");
  }
});
watch(
  () => route.params.id,
  (id) => {
    if (typeof id === "string" && id && current.value?.id !== id)
      void openConversation(id);
    if (!id && current.value) clearCurrent();
  },
  { immediate: true },
);
watch([() => messages.value.length, () => stream.value.partial], async () => {
  await nextTick();
  if (scroller.value) scroller.value.scrollTop = scroller.value.scrollHeight;
});

function newChat() {
  clearCurrent();
  draft.value = "";
  sidebarOpen.value = false;
  router.push("/chat");
  nextTick(() => composer.value?.focus());
}
function selectConversation(id: string) {
  sidebarOpen.value = false;
  router.push(`/chat/${id}`);
}
async function submit() {
  const text = draft.value.trim();
  if (!text || sending.value || busy.value) return;
  try {
    if (!current.value) {
      if (!selectedAgentId.value) {
        message.warning("请先选择 Agent");
        return;
      }
      const created = await createConversation(selectedAgentId.value);
      await router.replace(`/chat/${created.id}`);
    }
    if (await send(text)) {
      draft.value = "";
      await nextTick();
      composer.value?.focus();
    } else if (error.value) message.error(error.value);
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "发送失败");
  }
}
async function stopRun() {
  try {
    await stop();
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "停止失败");
  }
}
async function chooseApproval(id: string, approve: boolean) {
  try {
    await decideApproval(id, approve);
    message.success(approve ? "已同意，Agent 将继续执行" : "已拒绝");
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "处理失败");
  }
}
async function loadOlder() {
  const before = scroller.value?.scrollHeight || 0;
  try {
    await loadOlderMessages();
    await nextTick();
    if (scroller.value)
      scroller.value.scrollTop = scroller.value.scrollHeight - before;
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "加载历史失败");
  }
}
function askArchive(id: string) {
  dialog.warning({
    title: "归档对话",
    content: "对话将从列表中隐藏，运行记录仍保留。",
    positiveText: "归档",
    negativeText: "取消",
    onPositiveClick: async () => {
      try {
        await archive(id);
        if (route.params.id === id) router.push("/chat");
      } catch (cause) {
        message.error(cause instanceof Error ? cause.message : "归档失败");
      }
    },
  });
}
function openRename() {
  if (!current.value) return;
  renameDraft.value = current.value.title;
  renameOpen.value = true;
}
async function saveRename() {
  if (!renameDraft.value.trim()) return;
  try {
    await rename(renameDraft.value.trim());
    renameOpen.value = false;
  } catch (cause) {
    message.error(cause instanceof Error ? cause.message : "重命名失败");
  }
}
async function logout() {
  await auth.logout();
  router.replace("/login");
}
</script>

<template>
  <div class="client-shell">
    <div
      v-if="sidebarOpen"
      class="mobile-backdrop"
      @click="sidebarOpen = false"
    />
    <aside class="chat-sidebar" :class="{ open: sidebarOpen }">
      <div class="sidebar-top">
        <button class="client-brand" @click="newChat">
          <span class="brand-icon"><n-icon :component="SparklesOutline" /></span
          ><span>Agent Runtime</span></button
        ><button
          class="mobile-close"
          aria-label="关闭侧栏"
          @click="sidebarOpen = false"
        >
          <n-icon :component="CloseOutline" />
        </button>
      </div>
      <button class="new-chat" @click="newChat">
        <n-icon :component="AddOutline" /><span>开启新对话</span
        ><span class="new-chat-shortcut">⌘ K</span>
      </button>
      <div class="sidebar-search">
        <n-icon :component="SearchOutline" /><input
          v-model="search"
          placeholder="搜索对话"
          aria-label="搜索对话"
        />
      </div>
      <div class="conversation-area">
        <div class="list-heading">
          最近的对话 <span>{{ conversations.length }}</span>
        </div>
        <div v-if="!visibleConversations.length" class="sidebar-empty">
          {{ search ? "没有匹配的对话" : "你的对话将在这里出现" }}
        </div>
        <div
          v-for="item in visibleConversations"
          :key="item.id"
          class="conversation-row"
          :class="{ active: current?.id === item.id }"
        >
          <button
            class="conversation-link"
            @click="selectConversation(item.id)"
          >
            <span class="conversation-title">{{ item.title || "新对话" }}</span
            ><small>{{ item.agent.name }}</small></button
          ><button
            class="conversation-delete"
            :aria-label="`归档 ${item.title}`"
            @click="askArchive(item.id)"
          >
            <n-icon :component="TrashOutline" />
          </button>
        </div>
        <button
          v-if="hasMoreConversations && !search"
          class="load-more"
          @click="loadConversations(false)"
        >
          加载更多对话 <n-icon :component="ChevronDownOutline" />
        </button>
      </div>
      <div class="sidebar-profile">
        <span class="profile-avatar">{{
          (auth.user?.display_name || auth.user?.username || "U").slice(0, 1)
        }}</span
        ><span class="profile-name"
          ><strong>{{ auth.user?.display_name || auth.user?.username }}</strong
          ><small>个人工作空间</small></span
        ><button aria-label="个人资料" @click="profileOpen = true">
          <n-icon :component="EllipsisHorizontalOutline" />
        </button>
      </div>
    </aside>

    <div class="chat-main">
      <header class="chat-header">
        <div class="chat-header-left">
          <button
            class="sidebar-toggle"
            aria-label="打开侧栏"
            @click="sidebarOpen = true"
          >
            <n-icon :component="MenuOutline" />
          </button>
          <div class="header-agent-mark">
            <n-icon :component="SparklesOutline" />
          </div>
          <div class="header-agent">
            <strong>{{
              current?.agent.name || currentAgent?.name || "选择你的 Agent"
            }}</strong
            ><small>{{ current ? "专属对话空间" : "准备开始新的对话" }}</small>
          </div>
        </div>
        <div class="header-actions">
          <button
            v-if="current"
            title="重命名对话"
            aria-label="重命名对话"
            @click="openRename"
          >
            <n-icon :component="CreateOutline" /></button
          ><button
            title="会话文件"
            aria-label="会话文件"
            @click="artifactsOpen = true"
          >
            <n-icon :component="AttachOutline" /><span
              v-if="artifacts.length"
              class="artifact-count"
              >{{ artifacts.length }}</span
            >
          </button>
        </div>
      </header>
      <div ref="scroller" class="chat-scroll">
        <div v-if="!current && !loading" class="welcome">
          <div class="welcome-orbit">
            <div class="welcome-symbol">
              <n-icon :component="SparklesOutline" />
            </div>
          </div>
          <span class="welcome-eyebrow">A SPACE FOR YOUR IDEAS</span>
          <h1>今天，我们一起<br /><em>想些什么？</em></h1>
          <p>选择一个 Agent，描述你的问题。余下的事情，交给我们一起完成。</p>
          <div class="agent-search">
            <n-icon :component="SearchOutline" /><input
              v-model="agentSearch"
              placeholder="搜索 Agent"
              aria-label="搜索 Agent"
            />
          </div>
          <div class="agent-picker">
            <button
              v-for="agent in visibleAgents"
              :key="agent.id"
              class="agent-option"
              :class="{ selected: selectedAgentId === agent.id }"
              @click="selectedAgentId = agent.id"
            >
              <span class="agent-option-icon"
                ><n-icon :component="SparklesOutline" /></span
              ><strong>{{ agent.name }}</strong
              ><small>{{ agent.description || "随时准备帮你处理问题" }}</small
              ><span class="agent-select-arrow">↗</span>
            </button>
            <div v-if="!visibleAgents.length" class="empty-agents">
              {{
                agentSearch
                  ? "没有找到匹配的 Agent"
                  : "暂无可用 Agent，请联系管理员启用后再试。"
              }}
            </div>
          </div>
        </div>
        <n-spin v-else-if="loading" class="center-loader" size="large" />
        <div v-else class="thread">
          <button
            v-if="hasOlderMessages"
            class="older-messages"
            @click="loadOlder"
          >
            <n-icon :component="ArrowUpOutline" /> 加载更早的消息
          </button>
          <div v-if="!messages.length" class="conversation-start">
            <span class="conversation-start-icon"
              ><n-icon :component="SparklesOutline"
            /></span>
            <h2>对话已准备好</h2>
            <p>向 {{ current?.agent.name }} 发送第一条消息吧。</p>
          </div>
          <div
            v-for="item in messages"
            :key="item.id"
            class="message-row"
            :class="{
              mine: ['user', 'human'].includes(item.role.toLowerCase()),
            }"
          >
            <div
              v-if="!['user', 'human'].includes(item.role.toLowerCase())"
              class="message-avatar"
            >
              <n-icon :component="SparklesOutline" />
            </div>
            <div class="message-content">
              <div class="message-author">
                {{
                  ["user", "human"].includes(item.role.toLowerCase())
                    ? "你"
                    : current?.agent.name
                }}
              </div>
              <div class="message-text">{{ item.content }}</div>
            </div>
          </div>
          <div
            v-if="run && !isTerminal(run.status)"
            class="message-row streaming-row"
          >
            <div class="message-avatar">
              <n-icon :component="SparklesOutline" />
            </div>
            <div class="message-content">
              <div class="message-author">
                {{ current?.agent.name }}
                <span class="stream-status"
                  ><span class="breathing-dot" />{{ statusText
                  }}{{ reconnecting ? " · 重新连接中" : "" }}</span
                >
              </div>
              <div v-if="stream.partial" class="message-text">
                {{ stream.partial }}<span class="typing-caret" />
              </div>
              <div v-else class="thinking-indicator"><i /><i /><i /></div>
            </div>
          </div>
          <div v-if="pendingApprovals.length" class="approval-stack">
            <div
              v-for="approval in pendingApprovals"
              :key="approval.id"
              class="approval-card"
            >
              <div class="approval-top">
                <span class="approval-badge">需要你的确认</span
                ><span class="risk-label" :class="approval.risk.toLowerCase()"
                  >{{ approval.risk }} 风险</span
                >
              </div>
              <h3>{{ approval.title }}</h3>
              <p>{{ approval.description }}</p>
              <small>工具：{{ approval.tool_name }}</small>
              <div class="approval-actions">
                <n-button
                  size="small"
                  @click="chooseApproval(approval.id, false)"
                  >拒绝</n-button
                ><n-button
                  size="small"
                  type="primary"
                  @click="chooseApproval(approval.id, true)"
                  >同意并继续</n-button
                >
              </div>
            </div>
          </div>
          <div
            v-if="run && isTerminal(run.status) && run.status !== 'COMPLETED'"
            class="run-result"
          >
            <strong>{{ statusText }}</strong
            ><span>{{ run.error || "本次执行没有完成。" }}</span
            ><button
              v-if="lastUserContent"
              @click="
                draft = lastUserContent;
                submit();
              "
            >
              <n-icon :component="RefreshOutline" /> 再次发送
            </button>
          </div>
          <div v-if="artifacts.length" class="thread-artifacts">
            <span>本次会话的文件</span
            ><button
              v-for="artifact in artifacts.slice(0, 3)"
              :key="artifact.id"
              @click="artifactsOpen = true"
            >
              <n-icon :component="AttachOutline" /> {{ artifact.name }}
            </button>
          </div>
        </div>
      </div>
      <footer class="composer-dock">
        <div v-if="error" class="composer-error">
          {{ error }}
          <button
            v-if="run && !isTerminal(run.status)"
            @click="connectRun(run.id)"
          >
            重新连接
          </button>
        </div>
        <div class="composer">
          <textarea
            ref="composer"
            v-model="draft"
            :disabled="busy || sending"
            :placeholder="
              busy
                ? statusText + '…'
                : '向 ' +
                  (current?.agent.name || currentAgent?.name || 'Agent') +
                  ' 发送消息'
            "
            rows="2"
            aria-label="输入消息"
            @keydown.enter.exact.prevent="submit"
          />
          <div class="composer-bottom">
            <span>Enter 发送 · Shift + Enter 换行</span
            ><n-button
              v-if="busy"
              circle
              type="error"
              secondary
              aria-label="停止生成"
              @click="stopRun"
              ><template #icon
                ><n-icon :component="StopOutline" /></template></n-button
            ><n-button
              v-else
              circle
              type="primary"
              :disabled="
                !draft.trim() || sending || (!current && !selectedAgentId)
              "
              aria-label="发送消息"
              @click="submit"
              ><template #icon
                ><n-icon :component="PaperPlaneOutline" /></template
            ></n-button>
          </div>
        </div>
        <div class="composer-note">
          Agent 生成的内容可能有误，请核对重要信息。
        </div>
      </footer>
    </div>
    <artifact-viewer v-model:show="artifactsOpen" :artifacts="artifacts" />
    <n-modal
      v-model:show="renameOpen"
      preset="card"
      title="重命名对话"
      style="width: min(430px, 90vw)"
      ><n-input
        v-model:value="renameDraft"
        maxlength="200"
        placeholder="对话名称"
        @keyup.enter="saveRename"
      /><template #footer
        ><div class="modal-actions">
          <n-button @click="renameOpen = false">取消</n-button
          ><n-button type="primary" @click="saveRename">保存</n-button>
        </div></template
      ></n-modal
    >
    <n-modal
      v-model:show="profileOpen"
      preset="card"
      title="个人资料"
      style="width: min(430px, 90vw)"
      ><div class="profile-detail">
        <span class="profile-avatar large">{{
          (auth.user?.display_name || auth.user?.username || "U").slice(0, 1)
        }}</span>
        <div>
          <strong>{{ auth.user?.display_name || auth.user?.username }}</strong
          ><small>@{{ auth.user?.username }}</small>
        </div>
      </div>
      <template #footer
        ><div class="modal-actions">
          <n-button @click="profileOpen = false">关闭</n-button
          ><n-button type="error" secondary @click="logout"
            ><template #icon><n-icon :component="LogOutOutline" /></template
            >退出登录</n-button
          >
        </div></template
      ></n-modal
    >
  </div>
</template>
