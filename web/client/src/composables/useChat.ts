import { onUnmounted, ref } from "vue";
import { api, authorizedFetch } from "../api/http";
import { watchRunEvents } from "../stream/connect";
import { applyActivity, watchAguiEvents, type Activity } from "../stream/agui";
import { applyRunEvent, emptyRunState, isTerminal } from "../stream/state";
import type {
  Agent,
  Approval,
  Artifact,
  Conversation,
  Message,
  Page,
  Run,
  AcceptedMessage,
} from "../types/api";

const base = "/api/v1/client";
const activeKey = (conversationId: string) =>
  `client_active_run:${conversationId}`;

export function useChat() {
  const agents = ref<Agent[]>([]);
  const conversations = ref<Conversation[]>([]);
  const conversationPage = ref(1);
  const hasMoreConversations = ref(false);
  const current = ref<Conversation | null>(null);
  const messages = ref<Message[]>([]);
  const hasOlderMessages = ref(false);
  const run = ref<Run | null>(null);
  const stream = ref(emptyRunState());
  const approvals = ref<Approval[]>([]);
  const artifacts = ref<Artifact[]>([]);
  const activities = ref<Activity[]>([]);
  const activitiesByRun = ref<Record<string, Activity[]>>({});
  const loading = ref(false);
  const sending = ref(false);
  const reconnecting = ref(false);
  const error = ref("");
  let controller: AbortController | null = null;
  let selection = 0;

  async function loadAgents(): Promise<void> {
    agents.value = await api.get<Agent[]>(`${base}/agents`);
  }

  async function loadConversations(reset = true): Promise<void> {
    const page = reset ? 1 : conversationPage.value + 1;
    const result = await api.get<Page<Conversation>>(
      `${base}/conversations?page=${page}&page_size=20`,
    );
    conversations.value = reset
      ? result.items
      : [...conversations.value, ...result.items];
    conversationPage.value = page;
    hasMoreConversations.value = page * result.page_size < result.total;
  }

  async function loadMessages(before?: string): Promise<void> {
    if (!current.value) return;
    const id = current.value.id;
    const params = new URLSearchParams({ limit: "30" });
    if (before) params.set("before", before);
    const rows = await api.get<Message[]>(
      `${base}/conversations/${id}/messages?${params}`,
    );
    if (current.value?.id !== id) return;
    messages.value = before ? [...rows, ...messages.value] : rows;
    hasOlderMessages.value = rows.length === 30;
    await Promise.all(
      [
        ...new Set(
          rows
            .map((row) => row.run_id)
            .filter((runId): runId is string => !!runId),
        ),
      ].map((runId) => loadActivities(runId, id)),
    );
  }

  async function loadOlderMessages(): Promise<void> {
    const first = messages.value[0];
    if (first) await loadMessages(first.id);
  }

  async function loadArtifacts(): Promise<void> {
    if (!current.value) return;
    const id = current.value.id;
    const result = await api.get<Page<Artifact>>(
      `${base}/conversations/${id}/artifacts?page_size=100`,
    );
    if (current.value?.id === id) artifacts.value = result.items;
  }

  async function loadActivities(
    runId: string,
    conversationId = current.value?.id,
  ): Promise<void> {
    const previous = activitiesByRun.value[runId];
    const result = await api.get<{ items: Activity[] }>(
      `${base}/runs/${runId}/activity`,
    );
    // 若请求期间已收到更新快照，保留实时内容，避免旧历史覆盖正在输出的推理。
    if (
      current.value?.id !== conversationId ||
      activitiesByRun.value[runId] !== previous
    )
      return;
    activitiesByRun.value = { ...activitiesByRun.value, [runId]: result.items };
    if (run.value?.id === runId) activities.value = result.items;
  }

  async function loadApprovals(runId: string): Promise<void> {
    const result = await api.get<Approval[]>(`${base}/runs/${runId}/approvals`);
    if (run.value?.id === runId) approvals.value = result;
  }

  async function syncRun(runId: string): Promise<void> {
    const latest = await api.get<Run>(`${base}/runs/${runId}`);
    if (current.value?.id !== latest.conversation_id || run.value?.id !== runId)
      return;
    run.value = latest;
    stream.value = {
      ...stream.value,
      status: latest.status,
      partial:
        latest.status === "COMPLETED"
          ? (latest.answer ?? stream.value.partial)
          : isTerminal(latest.status)
            ? ""
            : stream.value.partial,
    };
    if (latest.status === "WAITING") await loadApprovals(runId);
    if (isTerminal(latest.status)) {
      approvals.value = [];
      sessionStorage.removeItem(activeKey(latest.conversation_id));
      await Promise.all([
        loadMessages(),
        loadConversations(),
        loadArtifacts(),
        loadActivities(runId),
      ]);
    }
  }

  function connectRun(runId: string): void {
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    stream.value = emptyRunState(run.value?.status || "PENDING");
    activities.value = activitiesByRun.value[runId] || [];
    reconnecting.value = false;
    if (import.meta.env.VITE_AGUI_ENABLED !== "false") {
      void watchAguiEvents({
        open: (cursor, streamSignal) =>
          authorizedFetch(`${base}/runs/${runId}/ag-ui/events`, {
            headers: cursor ? { "Last-Event-ID": cursor } : undefined,
            signal: streamSignal,
          }),
        onEvent: async (event) => {
          if (signal.aborted || run.value?.id !== runId) return;
          reconnecting.value = false;
          activities.value = applyActivity(activities.value, event);
          activitiesByRun.value = {
            ...activitiesByRun.value,
            [runId]: activities.value,
          };
          if (event.type === "RUN_STARTED")
            stream.value = { ...stream.value, status: "RUNNING" };
          if (event.type === "TEXT_MESSAGE_CONTENT")
            stream.value = {
              ...stream.value,
              partial: stream.value.partial + (event.delta || ""),
            };
          if (event.type === "ACTIVITY_SNAPSHOT") {
            if (event.activityType === "approval") await loadApprovals(runId);
            if (event.activityType === "artifact") await loadArtifacts();
          }
          if (event.type === "RUN_FINISHED" || event.type === "RUN_ERROR")
            await syncRun(runId);
        },
        onRetry: () => {
          if (!signal.aborted && run.value?.status !== "WAITING")
            reconnecting.value = true;
        },
        signal,
      }).catch((cause) => {
        if (!signal.aborted)
          error.value =
            cause instanceof Error ? cause.message : "AG-UI 连接失败";
      });
      return;
    }
    void watchRunEvents({
      open: (cursor, streamSignal) =>
        authorizedFetch(`${base}/runs/${runId}/events`, {
          headers: cursor ? { "Last-Event-ID": String(cursor) } : undefined,
          signal: streamSignal,
        }),
      onEvent: async (event) => {
        if (signal.aborted || run.value?.id !== runId) return;
        stream.value = applyRunEvent(stream.value, event);
        reconnecting.value = false;
        if (event.type === "approval.required" || event.type === "run.waiting")
          await loadApprovals(runId);
        if (isTerminal(stream.value.status)) await syncRun(runId);
      },
      onExpired: async () => {
        if (!signal.aborted) await syncRun(runId);
      },
      onRetry: () => {
        if (!signal.aborted) reconnecting.value = true;
      },
      signal,
    }).catch((cause) => {
      if (!signal.aborted)
        error.value = cause instanceof Error ? cause.message : "事件连接失败";
    });
  }

  async function openConversation(id: string): Promise<void> {
    const currentSelection = ++selection;
    controller?.abort();
    loading.value = true;
    error.value = "";
    run.value = null;
    stream.value = emptyRunState();
    approvals.value = [];
    artifacts.value = [];
    activities.value = [];
    activitiesByRun.value = {};
    messages.value = [];
    try {
      const detail = await api.get<Conversation>(`${base}/conversations/${id}`);
      if (currentSelection !== selection) return;
      current.value = detail;
      await Promise.all([loadMessages(), loadArtifacts()]);
      const activeRunId =
        [...messages.value].reverse().find((item) => item.run_id)?.run_id ||
        sessionStorage.getItem(activeKey(id));
      if (activeRunId) {
        const latest = await api.get<Run>(`${base}/runs/${activeRunId}`);
        if (currentSelection !== selection) return;
        run.value = latest;
        await loadActivities(activeRunId, id);
        if (currentSelection !== selection) return;
        if (isTerminal(latest.status)) await syncRun(activeRunId);
        else {
          if (latest.status === "WAITING") await loadApprovals(activeRunId);
          connectRun(activeRunId);
        }
      }
    } catch (cause) {
      if (currentSelection === selection)
        error.value = cause instanceof Error ? cause.message : "会话加载失败";
    } finally {
      if (currentSelection === selection) loading.value = false;
    }
  }

  async function createConversation(agentId: string): Promise<Conversation> {
    const created = await api.post<Conversation>(`${base}/conversations`, {
      agent_id: agentId,
    });
    await openConversation(created.id);
    void loadConversations().catch(() => {});
    return created;
  }

  async function send(content: string): Promise<boolean> {
    if (
      !current.value ||
      sending.value ||
      (run.value && !isTerminal(run.value.status))
    )
      return false;
    const text = content.trim();
    if (!text) return false;
    const conversationId = current.value.id;
    const clientMessageId = crypto.randomUUID();
    const optimistic: Message = {
      id: clientMessageId,
      role: "human",
      content: text,
      created_at: new Date().toISOString(),
    };
    messages.value.push(optimistic);
    sending.value = true;
    error.value = "";
    try {
      const accepted = await api.post<AcceptedMessage>(
        `${base}/conversations/${conversationId}/messages`,
        { client_message_id: clientMessageId, content: text },
      );
      if (current.value?.id !== conversationId) return true;
      optimistic.id = accepted.message.id;
      optimistic.run_id = accepted.run.id;
      run.value = {
        id: accepted.run.id,
        conversation_id: conversationId,
        status: accepted.run.status,
        answer: null,
        error: null,
        created_at: new Date().toISOString(),
        started_at: null,
        waiting_at: null,
        completed_at: null,
      };
      sessionStorage.setItem(activeKey(conversationId), accepted.run.id);
      connectRun(accepted.run.id);
      void loadConversations().catch(() => {});
      return true;
    } catch (cause) {
      messages.value = messages.value.filter(
        (message) => message !== optimistic,
      );
      error.value = cause instanceof Error ? cause.message : "发送失败";
      return false;
    } finally {
      sending.value = false;
    }
  }

  async function stop(): Promise<void> {
    if (!run.value) return;
    const latest = await api.post<Run>(`${base}/runs/${run.value.id}/cancel`);
    run.value = latest;
    stream.value = { ...stream.value, status: latest.status };
    if (isTerminal(latest.status)) await syncRun(latest.id);
  }

  async function decideApproval(
    approvalId: string,
    approve: boolean,
  ): Promise<void> {
    if (!run.value) return;
    await api.post(
      `${base}/approvals/${approvalId}/${approve ? "approve" : "reject"}`,
    );
    await loadApprovals(run.value.id);
    await syncRun(run.value.id);
    // 审批后的同一条 AG-UI 订阅会凭游标重连，避免 Worker 尚未领取时丢失恢复事件。
  }

  async function rename(title: string): Promise<void> {
    if (!current.value) return;
    current.value = await api.patch<Conversation>(
      `${base}/conversations/${current.value.id}`,
      { title },
    );
    await loadConversations();
  }

  async function archive(id: string): Promise<void> {
    await api.delete(`${base}/conversations/${id}`);
    if (current.value?.id === id) {
      controller?.abort();
      current.value = null;
      messages.value = [];
      run.value = null;
    }
    await loadConversations();
  }

  function clearCurrent(): void {
    ++selection;
    controller?.abort();
    current.value = null;
    messages.value = [];
    run.value = null;
    approvals.value = [];
    artifacts.value = [];
    activities.value = [];
    activitiesByRun.value = {};
    stream.value = emptyRunState();
    error.value = "";
  }

  onUnmounted(() => controller?.abort());
  return {
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
    activities,
    activitiesByRun,
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
  };
}
