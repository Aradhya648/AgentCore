import { describe, expect, it } from "vitest";
import { splitBriefContext } from "../AskCommenceParts";

describe("splitBriefContext", () => {
  it("returns empty for blank context", () => {
    expect(splitBriefContext("")).toEqual({ lead: "", points: [] });
    expect(splitBriefContext("  \n  ")).toEqual({ lead: "", points: [] });
  });

  it("uses first line as lead and strips bullet prefixes", () => {
    expect(
      splitBriefContext(
        "需求能做，但方向还差两处对齐。\n• 先按可执行起步计划开做\n- 确认后立刻动手",
      ),
    ).toEqual({
      lead: "需求能做，但方向还差两处对齐。",
      points: ["先按可执行起步计划开做", "确认后立刻动手"],
    });
  });

  it("handles a single-line context", () => {
    expect(splitBriefContext("只有一句说明")).toEqual({
      lead: "只有一句说明",
      points: [],
    });
  });
});
