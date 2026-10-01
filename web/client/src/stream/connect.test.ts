import { expect, it } from "vitest";
import { watchRunEvents } from "./connect";
import type { RunEvent } from "./state";

function response(text: string): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    }),
    { status: 200 },
  );
}

it("reconnects after a broken stream using the last received event ID", async () => {
  const cursors: number[] = [];
  const events: RunEvent[] = [];
  await watchRunEvents({
    open: async (cursor) => {
      cursors.push(cursor);
      return cursor === 0
        ? response(
            'id: 1\nevent: model.started\ndata: {"type":"model.started","sequence":1,"data":{"step_id":"s"}}\n\n',
          )
        : response(
            'id: 2\nevent: run.completed\ndata: {"type":"run.completed","sequence":2,"data":{"answer":"OK"}}\n\n',
          );
    },
    onEvent: (event) => {
      events.push(event);
    },
    onExpired: () => {
      throw new Error("unexpected 410");
    },
    signal: new AbortController().signal,
    retryDelay: async () => {},
  });
  expect(cursors).toEqual([0, 1]);
  expect(events.map((event) => event.type)).toEqual([
    "model.started",
    "run.completed",
  ]);
});

it("falls back to run snapshot when SSE history expired", async () => {
  let expired = false;
  await watchRunEvents({
    open: async () => new Response(null, { status: 410 }),
    onEvent: () => {
      throw new Error("unexpected event");
    },
    onExpired: () => {
      expired = true;
    },
    signal: new AbortController().signal,
  });
  expect(expired).toBe(true);
});
