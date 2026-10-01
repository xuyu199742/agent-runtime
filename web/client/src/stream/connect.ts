import { SseParser } from "./sse";
import { isTerminal, type RunEvent } from "./state";

interface WatchOptions {
  open: (cursor: number, signal: AbortSignal) => Promise<Response>;
  onEvent: (event: RunEvent) => void | Promise<void>;
  onExpired: () => void | Promise<void>;
  onRetry?: () => void;
  signal: AbortSignal;
  retryDelay?: (signal: AbortSignal) => Promise<void>;
}

function waitBeforeRetry(signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) {
      resolve();
      return;
    }
    const timer = setTimeout(done, 1200);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener("abort", done);
      resolve();
    }
    signal.addEventListener("abort", done, { once: true });
  });
}

export async function watchRunEvents(options: WatchOptions): Promise<void> {
  let cursor = 0;
  while (!options.signal.aborted) {
    try {
      const response = await options.open(cursor, options.signal);
      if (response.status === 410) {
        await options.onExpired();
        return;
      }
      if (response.status === 401 || response.status === 403)
        throw new Error("会话已失效或没有权限");
      if (!response.ok || !response.body)
        throw new Error(`事件连接失败 (${response.status})`);
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
            let event: RunEvent;
            try {
              event = JSON.parse(frame.data) as RunEvent;
            } catch {
              continue;
            }
            const sequence = Number(frame.id || event.sequence || 0);
            event.sequence = sequence;
            if (sequence > cursor) cursor = sequence;
            await options.onEvent(event);
            if (
              ["run.completed", "run.failed", "run.cancelled"].includes(
                event.type,
              )
            )
              return;
            if (
              event.type === "run.snapshot" &&
              isTerminal(String(event.data.status))
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
