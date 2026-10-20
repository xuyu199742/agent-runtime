import { SseParser } from "./sse";

export interface AguiEvent {
  type: string;
  messageId?: string;
  delta?: string;
  activityType?: string;
  content?: Record<string, unknown>;
  outcome?: { type?: string };
}

export interface Activity {
  id: string;
  type: string;
  content: Record<string, unknown>;
}

export function applyActivity(items: Activity[], event: AguiEvent): Activity[] {
  if (
    event.type !== "ACTIVITY_SNAPSHOT" ||
    !event.messageId ||
    !event.activityType
  )
    return items;
  const next = items.filter((item) => item.id !== event.messageId);
  return [
    ...next,
    {
      id: event.messageId,
      type: event.activityType,
      content: event.content || {},
    },
  ];
}

function waitBeforeRetry(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(done, 1200);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });
}

export async function watchAguiEvents(options: {
  open: (cursor: string, signal: AbortSignal) => Promise<Response>;
  onEvent: (event: AguiEvent) => void | Promise<void>;
  onRetry?: () => void;
  signal: AbortSignal;
  retryDelay?: (signal: AbortSignal) => Promise<void>;
}): Promise<void> {
  let cursor = "";
  while (!options.signal.aborted) {
    try {
      const response = await options.open(cursor, options.signal);
      if (response.status === 401 || response.status === 403)
        throw new Error("会话已失效或没有权限");
      if (!response.ok || !response.body)
        throw new Error(`AG-UI 连接失败 (${response.status})`);
      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      const parser = new SseParser();
      try {
        while (!options.signal.aborted) {
          const { done, value } = await reader.read();
          if (done) break;
          for (const frame of parser.push(
            decoder.decode(value, { stream: true }),
          )) {
            let event: AguiEvent;
            try {
              event = JSON.parse(frame.data) as AguiEvent;
            } catch {
              continue;
            }
            if (frame.id) cursor = frame.id;
            await options.onEvent(event);
            if (
              event.type === "RUN_ERROR" ||
              (event.type === "RUN_FINISHED" &&
                event.outcome?.type !== "interrupt")
            )
              return;
          }
        }
      } finally {
        if (options.signal.aborted) await reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    } catch (error) {
      if (options.signal.aborted) return;
      if (error instanceof Error && error.message === "会话已失效或没有权限")
        throw error;
    }
    if (!options.signal.aborted) {
      options.onRetry?.();
      await (options.retryDelay || waitBeforeRetry)(options.signal);
    }
  }
}
