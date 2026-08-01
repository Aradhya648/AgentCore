import { runPhaseLabel } from "@/components/assistantLabels";
import { describe, expect, it } from "vitest";

describe("runPhaseLabel", () => {
  it("maps worker activity phases to distinct Chinese badges", () => {
    expect(runPhaseLabel("thinking")).toBe("思考中");
    expect(runPhaseLabel("tool")).toBe("工具中");
    expect(runPhaseLabel("waiting_children")).toBe("等待子任务");
    expect(runPhaseLabel("winding_down")).toBe("收尾中");
  });

  it("returns null when phase absent (caller keeps 进行中 / queued / skipped)", () => {
    expect(runPhaseLabel(null)).toBeNull();
    expect(runPhaseLabel(undefined)).toBeNull();
  });
});
