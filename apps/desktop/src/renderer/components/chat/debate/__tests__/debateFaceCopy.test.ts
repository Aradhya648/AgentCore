import { describe, expect, it } from "vitest";
import {
  challengePreviewFromContext,
  debateFacePrimaryFromContext,
  firstSentence,
  pickAgentNodeIdlePrimary,
} from "../debateFaceCopy";

describe("firstSentence", () => {
  it("takes first sentence and truncates", () => {
    expect(firstSentence("成本是关键。后面还有很多。")).toBe("成本是关键。");
    expect(firstSentence("a".repeat(100), 20).endsWith("…")).toBe(true);
  });
});

describe("debateFacePrimaryFromContext", () => {
  it("prefers task block over round_focus", () => {
    expect(
      debateFacePrimaryFromContext([
        { channel: "round_focus", body: "旧焦点句。" },
        { channel: "task", body: "本轮请回应预算口径。补充证据。" },
      ]),
    ).toBe("本轮请回应预算口径。");
  });

  it("falls back to round_focus", () => {
    expect(
      debateFacePrimaryFromContext([
        { channel: "round_focus", body: "上线窗口是否过早。" },
      ]),
    ).toBe("上线窗口是否过早。");
  });

  it("returns null when empty", () => {
    expect(debateFacePrimaryFromContext([])).toBeNull();
    expect(debateFacePrimaryFromContext(undefined)).toBeNull();
  });
});

describe("challengePreviewFromContext", () => {
  it("extracts challenge first sentence", () => {
    expect(
      challengePreviewFromContext([
        { channel: "challenge", body: "未回应安全边界。其它。" },
      ]),
    ).toBe("未回应安全边界。");
  });
});

describe("pickAgentNodeIdlePrimary", () => {
  it("completed prefers output preview over role template", () => {
    expect(
      pickAgentNodeIdlePrimary({
        status: "completed",
        outputPreview: "我认为应暂缓上线…",
        task: "你在一场正反辩论中代表正方…",
        isDebate: true,
        debateFacePrimary: "本轮焦点句",
      }),
    ).toBe("我认为应暂缓上线…");
  });

  it("debate continuation without output uses face primary", () => {
    expect(
      pickAgentNodeIdlePrimary({
        status: "running",
        outputPreview: "",
        task: "你在一场正反辩论中代表正方…",
        isDebate: true,
        debateFacePrimary: "成本可控性",
      }),
    ).toBe("成本可控性");
  });

  it("debate completed without output or focus hides role template", () => {
    expect(
      pickAgentNodeIdlePrimary({
        status: "completed",
        outputPreview: "",
        task: "你在一场正反辩论中代表正方…",
        isDebate: true,
        debateFacePrimary: null,
      }),
    ).toBeNull();
  });

  it("non-debate keeps task", () => {
    expect(
      pickAgentNodeIdlePrimary({
        status: "completed",
        outputPreview: "",
        task: "起草方案",
        isDebate: false,
      }),
    ).toBe("起草方案");
  });
});
