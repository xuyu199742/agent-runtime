import { describe, expect, it } from "vitest";
import { applyRunEvent, emptyRunState } from "./state";

const event = (
  type: string,
  sequence: number,
  data: Record<string, unknown>,
) => ({ type, sequence, data });

describe("run event reconstruction", () => {
  it("replaces partial text when a crashed model step starts again", () => {
    let state = emptyRunState();
    state = applyRunEvent(
      state,
      event("model.started", 1, { step_id: "run:model:1" }),
    );
    state = applyRunEvent(
      state,
      event("model.delta", 2, { step_id: "run:model:1", text: "错误的" }),
    );
    state = applyRunEvent(
      state,
      event("model.started", 3, { step_id: "run:model:1" }),
    );
    state = applyRunEvent(
      state,
      event("model.delta", 4, { step_id: "run:model:1", text: "正确的" }),
    );
    expect(state.partial).toBe("正确的");
    expect(state.stepId).toBe("run:model:1");
  });

  it("ignores replayed event IDs and uses the canonical completed answer", () => {
    let state = emptyRunState();
    state = applyRunEvent(
      state,
      event("model.started", 1, { step_id: "step" }),
    );
    state = applyRunEvent(
      state,
      event("model.delta", 2, { step_id: "step", text: "A" }),
    );
    state = applyRunEvent(
      state,
      event("model.delta", 2, { step_id: "step", text: "A" }),
    );
    state = applyRunEvent(
      state,
      event("run.completed", 3, { answer: "Answer" }),
    );
    expect(state.partial).toBe("Answer");
    expect(state.status).toBe("COMPLETED");
    expect(state.sequence).toBe(3);
  });

  it("exposes waiting and approval events", () => {
    let state = applyRunEvent(emptyRunState(), event("run.waiting", 1, {}));
    state = applyRunEvent(
      state,
      event("approval.required", 2, { id: "approval-1" }),
    );
    expect(state.status).toBe("WAITING");
    expect(state.hasApproval).toBe(true);
  });

  it("clears pending approval and partial output after a recovery failure", () => {
    let state = applyRunEvent(emptyRunState(), event("run.waiting", 1, {}));
    state = applyRunEvent(state, event("approval.required", 2, {}));
    state = applyRunEvent(
      state,
      event("model.started", 3, { step_id: "step" }),
    );
    state = applyRunEvent(
      state,
      event("model.delta", 4, { step_id: "step", text: "partial" }),
    );
    state = applyRunEvent(
      state,
      event("run.failed", 5, { code: "APPROVAL_RECOVERY_LOST" }),
    );
    expect(state.status).toBe("FAILED");
    expect(state.hasApproval).toBe(false);
    expect(state.partial).toBe("");
  });

  it("drops stale partial output when reconnect snapshot is terminal", () => {
    let state = applyRunEvent(
      emptyRunState(),
      event("model.started", 1, { step_id: "step" }),
    );
    state = applyRunEvent(
      state,
      event("model.delta", 2, { step_id: "step", text: "old" }),
    );
    state = applyRunEvent(
      state,
      event("run.snapshot", 3, { status: "FAILED" }),
    );
    expect(state.partial).toBe("");
  });
});
