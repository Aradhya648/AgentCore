/**
 * ``test_run`` over-budget (验证未完成): ``display.budget_exceeded === true``.
 * Soft guidance / warning chrome — not the same red fault path as a real verify fail.
 */
export function isVerifyBudgetExceeded(display: unknown): boolean {
  if (!display || typeof display !== "object") return false;
  return (display as { budget_exceeded?: unknown }).budget_exceeded === true;
}
