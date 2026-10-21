import { describe, expect, it } from "vitest";
import { runErrorText } from "./errors";

describe("run error copy", () => {
  it("explains fail-closed recovery errors without suggesting an automatic retry", () => {
    expect(runErrorText("APPROVAL_RECOVERY_LOST")).toContain("检查点已丢失");
    expect(runErrorText("TOOL_RESULT_UNAVAILABLE")).toContain("缺少可重放结果");
    expect(runErrorText("REASONING_CONTEXT_MISSING")).toContain(
      "旧任务缺少推理上下文",
    );
    expect(runErrorText("MODEL_ERROR")).toContain("核对运行记录");
  });
});
