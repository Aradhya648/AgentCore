import { describe, expect, it } from "vitest";
import { EXEC_TIMEOUT_CAP_S } from "../fs/constants";

describe("EXEC_TIMEOUT_CAP_S", () => {
  it("covers test_run verify budget (300) + engine slack (30)", () => {
    expect(EXEC_TIMEOUT_CAP_S).toBeGreaterThanOrEqual(330);
  });
});
