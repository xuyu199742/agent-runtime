import { onUnmounted, ref } from "vue";
import { api, authorizedFetch } from "../api/http";
import { watchRunEvents } from "../stream/connect";
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

  async function loadApprovals(runId: string): Promise<void> {
    approvals.value = await api.get<Approval[]>(
      `${base}/runs/${runId}/approvals`,
    );
  }

  async function syncRun(runId: string): Promise<void> {
    const latest = await api.get<Run>(`${base}/runs/${runId}`);
    if (current.value?.id !== latest.conversation_id) return;
    run.value = latest;
    stream.value = {
      ...stream.value,
      status: latest.status,
      partial: latest.answer ?? stream.value.partial,
    };
    if (latest.status === "WAITING") await loadApprovals(runId);
    if (isTerminal(latest.status)) {
      sessionStorage.removeItem(activeKey(latest.conversation_id));
      await Promise.all([loadMessages(), loadConversations(), loadArtifacts()]);
    }
  }

  function connectRun(runId: string): void {
    controller?.abort();
    controller = new AbortController();
    const signal = controller.signal;
    stream.value = emptyRunState(run.value?.status || "PENDING");
    reconnecting.value = false;
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
    messages.value = [];
    try {
      const detail = await api.get<Conversation>(`${base}/conversations/${id}`);
      if (currentSelection !== selection) return;
      current.value = detail;
      await Promise.all([loadMessages(), loadArtifacts()]);
      const activeRunId = sessionStorage.getItem(activeKey(id));
      if (activeRunId) {
        const latest = await api.get<Run>(`${base}/runs/${activeRunId}`);
        if (currentSelection !== selection) return;
        run.value = latest;
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
