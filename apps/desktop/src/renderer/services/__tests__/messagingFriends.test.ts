import { normalizeWhoCanDm } from "@/services/messaging";
import { describe, expect, it } from "vitest";

describe("normalizeWhoCanDm", () => {
  it("maps legacy contacts to friends", () => {
    expect(normalizeWhoCanDm("contacts")).toBe("friends");
  });

  it("keeps friends and anyone", () => {
    expect(normalizeWhoCanDm("friends")).toBe("friends");
    expect(normalizeWhoCanDm("anyone")).toBe("anyone");
  });

  it("defaults unknown / empty to anyone", () => {
    expect(normalizeWhoCanDm(null)).toBe("anyone");
    expect(normalizeWhoCanDm(undefined)).toBe("anyone");
    expect(normalizeWhoCanDm("weird")).toBe("anyone");
  });
});
