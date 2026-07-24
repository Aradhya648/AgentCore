import type { ProcessStep } from "@agentcore/contract-types";
import { describe, expect, it } from "vitest";
import { formatMessageExport, formatProcessExport } from "../messageExport";

const steps: ProcessStep[] = [
  { kind: "reasoning", text: "先查资料" },
  {
    kind: "tool",
    id: "t1",
    tool_name: "web_search",
    arguments: { query: "AgentCore" },
    result: "ok",
    status: "success",
  },
  { kind: "content", text: "我先看一下。" },
  { kind: "content", text: "最终方案如下。" },
];

describe("formatMessageExport (mobile)", () => {
  it("defaults to deliverable-only", () => {
    expect(formatMessageExport("最终方案如下。", steps, "deliverable")).toBe(
      "最终方案如下。",
    );
  });

  it("includes process without duplicating trailing deliverable", () => {
    const text = formatMessageExport("最终方案如下。", steps, "with_process");
    expect(text.startsWith("【过程】")).toBe(true);
    expect(text).toContain("Search web");
    expect(text).not.toContain("【交付】");
  });

  it("formats process tools", () => {
    expect(formatProcessExport(steps)).toContain("AgentCore");
  });
});
