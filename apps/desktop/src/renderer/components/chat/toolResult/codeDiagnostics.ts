/**
 * Inner-loop ``code_diagnostics`` display (类型诊断): rides ``tool_use_end.display``
 * as an opaque Record — either as the whole display (``kind: "code_diagnostics"``)
 * or nested under write-tool display. Distinct from outer-loop ``test_run``
 * ``budget_exceeded`` (验证未完成).
 */

export type CodeDiagnosticSeverity = "error" | "warning" | "info";

export interface CodeDiagnosticItem {
  path: string;
  line: number;
  column: number;
  severity: CodeDiagnosticSeverity;
  message: string;
  code?: string;
}

export interface CodeDiagnosticsDisplay {
  kind: "code_diagnostics";
  status: "ok" | "unavailable";
  reason?: string;
  diagnostics: CodeDiagnosticItem[];
}

const SEVERITIES = new Set<string>(["error", "warning", "info"]);

function isDiagnosticItem(v: unknown): v is CodeDiagnosticItem {
  if (!v || typeof v !== "object") return false;
  const x = v as Record<string, unknown>;
  return (
    typeof x.path === "string" &&
    typeof x.line === "number" &&
    typeof x.column === "number" &&
    typeof x.severity === "string" &&
    SEVERITIES.has(x.severity) &&
    typeof x.message === "string"
  );
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

function normalize(d: CodeDiagnosticsDisplay): CodeDiagnosticsDisplay {
  return {
    kind: "code_diagnostics",
    status: d.status,
    reason: typeof d.reason === "string" ? d.reason : undefined,
    diagnostics: d.diagnostics.filter(isDiagnosticItem),
  };
}

/**
 * Pull code_diagnostics from a tool ``display``: top-level ``kind``, or nested
 * under ``code_diagnostics`` (write tools may attach diagnostics beside other fields).
 */
export function extractCodeDiagnostics(
  display: unknown,
): CodeDiagnosticsDisplay | null {
  if (!display || typeof display !== "object") return null;
  if (isCodeDiagnosticsDisplay(display)) return normalize(display);
  const nested = (display as { code_diagnostics?: unknown }).code_diagnostics;
  if (isCodeDiagnosticsDisplay(nested)) return normalize(nested);
  return null;
}

export function codeDiagnosticsErrorCount(
  display: CodeDiagnosticsDisplay,
): number {
  return display.diagnostics.filter((d) => d.severity === "error").length;
}

/** One-line peek: 「N 个类型错误」/ unavailable / clean. */
export function codeDiagnosticsPeek(display: CodeDiagnosticsDisplay): string {
  if (display.status === "unavailable") {
    return display.reason?.trim() || "类型诊断不可用";
  }
  const n = codeDiagnosticsErrorCount(display);
  if (n > 0) return `${n} 个类型错误`;
  return "未发现类型错误";
}
