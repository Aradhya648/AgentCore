/**
 * Inner-loop ``code_diagnostics`` display (类型诊断).
 * Mirror of desktop ``toolResult/codeDiagnostics`` (各端全新建；零共享业务逻辑).
 * Distinct from outer-loop ``test_run`` ``budget_exceeded`` (验证未完成).
 */

export interface CodeDiagnosticsDisplay {
  kind: "code_diagnostics";
  status: "ok" | "unavailable";
  reason?: string;
  diagnostics: Array<{
    path: string;
    line: number;
    column: number;
    severity: "error" | "warning" | "info";
    message: string;
    code?: string;
  }>;
}

/** True when ``d`` is a code_diagnostics display (top-level shape). */
export function isCodeDiagnosticsDisplay(
  d: unknown,
): d is CodeDiagnosticsDisplay {
  if (!d || typeof d !== "object") return false;
  const x = d as Record<string, unknown>;
  if (x.kind !== "code_diagnostics") return false;
  if (x.status !== "ok" && x.status !== "unavailable") return false;
  if (!Array.isArray(x.diagnostics)) return false;
  return true;
}

/**
 * Pull code_diagnostics from a tool ``display``: top-level ``kind``, or nested
 * under ``code_diagnostics``.
 */
export function extractCodeDiagnostics(
  display: unknown,
): CodeDiagnosticsDisplay | null {
  if (!display || typeof display !== "object") return null;
  if (isCodeDiagnosticsDisplay(display)) return display;
  const nested = (display as { code_diagnostics?: unknown }).code_diagnostics;
  if (isCodeDiagnosticsDisplay(nested)) return nested;
  return null;
}

export function codeDiagnosticsErrorCount(
  display: CodeDiagnosticsDisplay,
): number {
  return display.diagnostics.filter((d) => d.severity === "error").length;
}

/** Short banner / status line — never「验证未完成（预算耗尽）」. */
export function codeDiagnosticsSummary(
  display: CodeDiagnosticsDisplay,
): string {
  if (display.status === "unavailable") {
    return display.reason?.trim() || "类型诊断暂不可用";
  }
  const n = codeDiagnosticsErrorCount(display);
  if (n > 0) return `${n} 个类型错误`;
  return "未发现类型错误";
}
