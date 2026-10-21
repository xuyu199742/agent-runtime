import { expect, it } from "vitest";
import { applyActivity, watchAguiEvents, type Activity } from "./agui";

function response(text: string): Response {
  return new Response(
    new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    }),
  );
}

it("reconnects with the exact cursor and upserts repeated tool activity", async () => {
  const cursors: string[] = [];
  let activities: Activity[] = [];
  await watchAguiEvents({
    open: async (cursor) => {
      cursors.push(cursor);
      return cursor
        ? response(
            'id: 3:1\nevent: ACTIVITY_SNAPSHOT\ndata: {"type":"ACTIVITY_SNAPSHOT","messageId":"tool:one","activityType":"tool","content":{"status":"COMPLETED"}}\n\nid: 4:0\nevent: RUN_FINISHED\ndata: {"type":"RUN_FINISHED"}\n\n',
          )
        : response(
            'id: 2:1\nevent: ACTIVITY_SNAPSHOT\ndata: {"type":"ACTIVITY_SNAPSHOT","messageId":"tool:one","activityType":"tool","content":{"status":"RUNNING"}}\n\n',
          );
    },
    onEvent: (event) => {
      activities = applyActivity(activities, event);
    },
    signal: new AbortController().signal,
    retryDelay: async () => {},
  });
  expect(cursors).toEqual(["", "2:1"]);
  expect(activities).toEqual([
    { id: "tool:one", type: "tool", content: { status: "COMPLETED" } },
  ]);
});

it("keeps watching after an approval interrupt and resumes from its cursor", async () => {
  const cursors: string[] = [];
  await watchAguiEvents({
    open: async (cursor) => {
      cursors.push(cursor);
      return cursor
        ? response(
            'id: 8:0\nevent: ACTIVITY_SNAPSHOT\ndata: {"type":"ACTIVITY_SNAPSHOT","messageId":"approval:a","activityType":"approval","content":{"status":"APPROVED"}}\n\nid: 8:t:0\nevent: RUN_FINISHED\ndata: {"type":"RUN_FINISHED"}\n\n',
          )
        : response(
            'id: 7:t:0\nevent: RUN_FINISHED\ndata: {"type":"RUN_FINISHED","outcome":{"type":"interrupt"}}\n\n',
          );
    },
    onEvent: () => {},
    signal: new AbortController().signal,
    retryDelay: async () => {},
  });
  expect(cursors).toEqual(["", "7:t:0"]);
});
