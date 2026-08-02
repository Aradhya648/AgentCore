import { normalizeWhoCanDm } from "@/services/messaging";
import { describe, expect, it } from "vitest";

describe("normalizeWhoCanDm", () => {
  it("keeps friends and anyone", () => {
    expect(normalizeWhoCanDm("friends")).toBe("friends");
    expect(normalizeWhoCanDm("anyone")).toBe("anyone");
  });

  it("defaults unknown / empty / legacy contacts to anyone", () => {
    expect(normalizeWhoCanDm(null)).toBe("anyone");
    expect(normalizeWhoCanDm(undefined)).toBe("anyone");
    expect(normalizeWhoCanDm("weird")).toBe("anyone");
    expect(normalizeWhoCanDm("contacts")).toBe("anyone");
  });
});
