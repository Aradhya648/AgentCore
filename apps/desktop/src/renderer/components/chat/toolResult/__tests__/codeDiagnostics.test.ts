import { describe, expect, it } from "vitest";
import {
  codeDiagnosticsErrorCount,
  codeDiagnosticsPeek,
  extractCodeDiagnostics,
  isCodeDiagnosticsDisplay,
} from "../codeDiagnostics";

const sampleOk = {
  kind: "code_diagnostics" as const,
  status: "ok" as const,
  diagnostics: [
    {
      path: "a.ts",
      line: 10,
      column: 2,
      severity: "error" as const,
      message: "Type 'string' is not assignable",
      code: "TS2322",
    },
    {
      path: "b.ts",
      line: 1,
      column: 1,
      severity: "warning" as const,
      message: "unused",
    },
  ],
};

describe("codeDiagnostics", () => {
  it("recognizes top-level kind shape", () => {
    expect(isCodeDiagnosticsDisplay(sampleOk)).toBe(true);
    expect(isCodeDiagnosticsDisplay({ budget_exceeded: true })).toBe(false);
    expect(isCodeDiagnosticsDisplay({ kind: "browser" })).toBe(false);
  });

  it("extracts nested under write-tool display", () => {
    const nested = extractCodeDiagnostics({
      path: "a.ts",
      code_diagnostics: sampleOk,
    });
    expect(nested).toBeTruthy();
    if (!nested) return;
    expect(nested.kind).toBe("code_diagnostics");
    expect(codeDiagnosticsErrorCount(nested)).toBe(1);
  });

  it("peek says N 个类型错误 / clean / unavailable", () => {
    expect(codeDiagnosticsPeek(sampleOk)).toBe("1 个类型错误");
    expect(
      codeDiagnosticsPeek({
        kind: "code_diagnostics",
        status: "ok",
        diagnostics: [],
      }),
    ).toBe("未发现类型错误");
    expect(
      codeDiagnosticsPeek({
        kind: "code_diagnostics",
        status: "unavailable",
        reason: "LSP 未就绪",
        diagnostics: [],
      }),
    ).toBe("LSP 未就绪");
  });
});
