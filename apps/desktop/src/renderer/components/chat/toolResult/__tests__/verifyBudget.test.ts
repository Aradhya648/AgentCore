import { describe, expect, it } from "vitest";
import { isVerifyBudgetExceeded } from "../verifyBudget";

describe("isVerifyBudgetExceeded", () => {
  it("true only when display.budget_exceeded === true", () => {
    expect(isVerifyBudgetExceeded({ budget_exceeded: true })).toBe(true);
    expect(isVerifyBudgetExceeded({ budget_exceeded: false })).toBe(false);
    expect(isVerifyBudgetExceeded({ exit_code: -1 })).toBe(false);
    expect(isVerifyBudgetExceeded(null)).toBe(false);
    expect(isVerifyBudgetExceeded(undefined)).toBe(false);
  });
});
