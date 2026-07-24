import { afterEach, describe, expect, it, vi } from "vitest";
import {
  LAYOUT_FAILURE_USER_MESSAGE,
  describeLayoutFailure,
  logLayoutFailure,
} from "../layoutFailure";

describe("describeLayoutFailure", () => {
  it("prefers Error.message", () => {
    expect(describeLayoutFailure(new Error("ELK boom"))).toBe("ELK boom");
  });

  it("trims blank Error.message to fallback", () => {
    expect(describeLayoutFailure(new Error("   "))).toBe(
      LAYOUT_FAILURE_USER_MESSAGE,
    );
  });

  it("accepts plain strings", () => {
    expect(describeLayoutFailure("timeout")).toBe("timeout");
  });

  it("falls back for unknown shapes", () => {
    expect(describeLayoutFailure(null)).toBe(LAYOUT_FAILURE_USER_MESSAGE);
    expect(describeLayoutFailure({ code: 1 })).toBe(
      LAYOUT_FAILURE_USER_MESSAGE,
    );
  });
});

describe("logLayoutFailure", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("logs and returns the described message", () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const message = logLayoutFailure(new Error("layout exploded"), {
      turnId: "t1",
    });
    expect(message).toBe("layout exploded");
    expect(spy).toHaveBeenCalled();
    const tag = String(spy.mock.calls[0]?.[0] ?? "");
    expect(tag).toContain("graph.layout_failed");
  });
});
