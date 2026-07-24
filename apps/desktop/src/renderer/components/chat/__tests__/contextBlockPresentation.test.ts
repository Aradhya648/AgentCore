import { describe, expect, it } from "vitest";
import {
  COPY_CONTEXT_CHANNELS,
  contextBlockSummaryLine,
  isCopyContextChannel,
} from "../contextBlockPresentation";

describe("isCopyContextChannel", () => {
  it("whitelist matches decision copy-type channels only", () => {
    expect([...COPY_CONTEXT_CHANNELS].sort()).toEqual([
      "dependency",
      "history",
      "opponent",
      "request",
      "team_result",
    ]);
    for (const ch of COPY_CONTEXT_CHANNELS) {
      expect(isCopyContextChannel(ch)).toBe(true);
    }
  });

  it("rejects incremental and debate-structure channels", () => {
    for (const ch of [
      "team_position",
      "workspace",
      "deliverable",
      "team_brief",
      "steer",
      "system",
      "task",
      "round_focus",
      "challenge",
      "interjection",
      "cross_exam",
      "closing",
      "continuation",
    ]) {
      expect(isCopyContextChannel(ch)).toBe(false);
    }
  });

  it("does not classify by body text", () => {
    // Same body as a dependency would carry — channel alone decides.
    expect(isCopyContextChannel("workspace")).toBe(false);
    expect(isCopyContextChannel("dependency")).toBe(true);
  });
});

describe("contextBlockSummaryLine", () => {
  it("returns the first non-empty line", () => {
    expect(contextBlockSummaryLine("\n  \n首行摘要\n第二行")).toBe("首行摘要");
  });

  it("returns empty string for blank body", () => {
    expect(contextBlockSummaryLine("  \n\n")).toBe("");
  });
});
