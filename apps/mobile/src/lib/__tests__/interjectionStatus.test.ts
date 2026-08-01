import {
  interjectionStatusLabel,
  interjectionStatusTone,
} from "@/lib/interjectionStatus";
import { describe, expect, it } from "vitest";

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
    ]) {
      expect(interjectionStatusLabel(s)).not.toContain("已传达给团队");
    }
  });
});

describe("interjectionStatusTone", () => {
  it("addressed is muted read-sense, not success", () => {
    expect(interjectionStatusTone("addressed")).toBe("addressed");
    expect(interjectionStatusTone("delivered")).toBe("received");
  });
});
