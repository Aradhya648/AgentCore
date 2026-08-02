import { describe, expect, it } from "vitest";
import {
  codeDiagnosticsErrorCount,
  codeDiagnosticsSummary,
  extractCodeDiagnostics,
  isCodeDiagnosticsDisplay,
} from "../codeDiagnostics";

describe("codeDiagnostics (mobile)", () => {
  it("recognizes top-level shape and rejects budget_exceeded", () => {
    expect(
      isCodeDiagnosticsDisplay({
        kind: "code_diagnostics",
        status: "ok",
        diagnostics: [],
      }),
    ).toBe(true);
    expect(isCodeDiagnosticsDisplay({ budget_exceeded: true })).toBe(false);
  });

  it("summarizes errors without reuse of 验证未完成文案", () => {
    const d = extractCodeDiagnostics({
      kind: "code_diagnostics",
      status: "ok",
      diagnostics: [
        {
          path: "a.ts",
          line: 1,
          column: 1,
          severity: "error",
          message: "boom",
          code: "TS2322",
        },
        {
          path: "b.ts",
          line: 2,
          column: 1,
          severity: "warning",
          message: "unused",
        },
      ],
    });
    expect(d).not.toBeNull();
    if (!d) return;
    expect(codeDiagnosticsErrorCount(d)).toBe(1);
    const summary = codeDiagnosticsSummary(d);
    expect(summary).toBe("1 个类型错误");
    expect(summary).not.toContain("验证未完成");
    expect(summary).not.toContain("预算耗尽");
  });

  it("summarizes clean ok as 未发现类型错误", () => {
    expect(
      codeDiagnosticsSummary({
        kind: "code_diagnostics",
        status: "ok",
        diagnostics: [],
      }),
    ).toBe("未发现类型错误");
  });

  it("summarizes unavailable with reason", () => {
    expect(
      codeDiagnosticsSummary({
        kind: "code_diagnostics",
        status: "unavailable",
        reason: "工作区无 LSP",
        diagnostics: [],
      }),
    ).toBe("工作区无 LSP");
  });

  it("summarizes unavailable without reason as 类型诊断暂不可用", () => {
    expect(
      codeDiagnosticsSummary({
        kind: "code_diagnostics",
        status: "unavailable",
        diagnostics: [],
      }),
    ).toBe("类型诊断暂不可用");
  });
});
