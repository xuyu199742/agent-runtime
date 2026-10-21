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

it("replaces cumulative model snapshots without duplicating reasoning or moving steps", () => {
  let items: Activity[] = [];
  const snapshot = (
    id: string,
    type: string,
    content: Record<string, unknown>,
  ) => ({
    type: "ACTIVITY_SNAPSHOT",
    messageId: id,
    activityType: type,
    content,
  });
  items = applyActivity(
    items,
    snapshot("model:1", "model", {
      text: "",
      reasoning: "先检查",
      status: "RUNNING",
    }),
  );
  items = applyActivity(
    items,
    snapshot("tool:1", "tool", {
      name: "search",
      input: { query: "资料" },
      status: "RUNNING",
    }),
  );
  const update = snapshot("model:1", "model", {
    text: "完成",
    reasoning: "先检查，再分析",
    status: "COMPLETED",
  });
  items = applyActivity(items, update);
  items = applyActivity(items, update);
  expect(items.map((item) => item.id)).toEqual(["model:1", "tool:1"]);
  expect(items[0]?.content.reasoning).toBe("先检查，再分析");
  expect(items[0]?.content.text).toBe("完成");
});

it("preserves tool failure details and only records explicit skill reads", () => {
  const snapshot = (
    id: string,
    type: string,
    content: Record<string, unknown>,
  ) => ({
    type: "ACTIVITY_SNAPSHOT",
    messageId: id,
    activityType: type,
    content,
  });
  let items = applyActivity(
    [],
    snapshot("tool:read", "tool", {
      name: "read_skill",
      status: "FAILED",
      error: "资源不存在",
    }),
  );
  expect(items.some((item) => item.type === "skill")).toBe(false);
  items = applyActivity(
    items,
    snapshot("skill:1", "skill", {
      name: "review",
      status: "LOADED",
      resource: "SKILL.md",
      revision: "abc",
      contentHash: "hash",
    }),
  );
  expect(items[0]?.content.error).toBe("资源不存在");
  expect(items[1]?.content).toEqual({
    name: "review",
    status: "LOADED",
    resource: "SKILL.md",
    revision: "abc",
    contentHash: "hash",
  });
});
