/**
 * ``test_run`` over-budget (验证未完成): ``display.budget_exceeded === true``.
 * Mirror of desktop ``toolResult/verifyBudget`` (各端全新建；零共享业务逻辑).
 */
export function isVerifyBudgetExceeded(display: unknown): boolean {
  if (!display || typeof display !== "object") return false;
  return (display as { budget_exceeded?: unknown }).budget_exceeded === true;
}
