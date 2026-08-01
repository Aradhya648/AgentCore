import { describe, expect, it } from "vitest";
import {
  interjectionStatusLabel,
  interjectionStatusTone,
} from "../interjectionStatus";

describe("interjectionStatusLabel", () => {
  it("maps S1 four states + legacy delivered", () => {
    expect(interjectionStatusLabel("received")).toBe("主 Agent 已收到");
    expect(interjectionStatusLabel("delivered")).toBe("主 Agent 已收到");
    expect(interjectionStatusLabel("queued")).toBe("将在下一条回复处理");
    expect(interjectionStatusLabel("failed")).toBe(
      "未能排队，请重试或再说一次",
    );
    expect(interjectionStatusLabel("addressed")).toBe("主 Agent 已回应");
  });

  it("never says 已传达给团队", () => {
    for (const s of [
      "received",
      "delivered",
      "queued",
      "failed",
      "addressed",
      "unknown",
    ]) {
      expect(interjectionStatusLabel(s)).not.toContain("已传达给团队");
    }
  });
});

describe("interjectionStatusTone", () => {
  it("addressed is not success-green tone", () => {
    expect(interjectionStatusTone("addressed")).toBe("addressed");
    expect(interjectionStatusTone("received")).toBe("received");
    expect(interjectionStatusTone("delivered")).toBe("received");
    expect(interjectionStatusTone("queued")).toBe("queued");
    expect(interjectionStatusTone("failed")).toBe("failed");
  });
});
