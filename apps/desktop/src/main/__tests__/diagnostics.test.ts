/**
 * diagnostics workspace op — pure helpers + small LanguageService sample.
 * @vitest-environment node
 */
import { mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import type { StoredRoot } from "../fs/roots";
import {
  type DiagnosticsValue,
  _clearDiagnosticsCacheForTests,
  emptyOk,
  isTsJsPath,
  mapDiagnosticSeverity,
  opDiagnostics,
  parsePathsArg,
  unavailable,
} from "../fs/workspace/diagnostics";
import { sessionRootAccessError } from "../fs/workspace/dispatch";

describe("diagnostics pure helpers", () => {
  it("mapDiagnosticSeverity maps TS categories", () => {
    expect(mapDiagnosticSeverity(1)).toBe("error");
    expect(mapDiagnosticSeverity(0)).toBe("warning");
    expect(mapDiagnosticSeverity(2)).toBe("info");
    expect(mapDiagnosticSeverity(3)).toBe("info");
    expect(mapDiagnosticSeverity(99)).toBeNull();
  });

  it("isTsJsPath accepts TS/JS extensions only", () => {
    expect(isTsJsPath("src/a.ts")).toBe(true);
    expect(isTsJsPath("src/a.tsx")).toBe(true);
    expect(isTsJsPath("src/a.js")).toBe(true);
    expect(isTsJsPath("src/a.mjs")).toBe(true);
    expect(isTsJsPath("src/a.cts")).toBe(true);
    expect(isTsJsPath("readme.md")).toBe(false);
    expect(isTsJsPath("src/a.py")).toBe(false);
  });

  it("unavailable / emptyOk shapes", () => {
    expect(unavailable("工作区未找到 tsconfig.json")).toEqual({
      status: "unavailable",
      reason: "工作区未找到 tsconfig.json",
      diagnostics: [],
    });
    expect(emptyOk()).toEqual({ status: "ok", diagnostics: [] });
  });

  it("parsePathsArg normalizes and drops junk", () => {
    expect(parsePathsArg({ paths: [] })).toEqual([]);
    expect(
      parsePathsArg({ paths: ["a.ts", "  ", "b\\c.tsx", 1, null, "d.js"] }),
    ).toEqual(["a.ts", "b/c.tsx", "d.js"]);
    expect(parsePathsArg({})).toEqual([]);
  });
});

describe("opDiagnostics", () => {
  let dir: string;
  let root: StoredRoot;

  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "diag-")));
    root = { id: "d", name: "d", absPath: dir };
    _clearDiagnosticsCacheForTests();
  });

  afterEach(async () => {
    _clearDiagnosticsCacheForTests();
    await rm(dir, { recursive: true, force: true });
  });

  it("empty paths → ok + empty diagnostics", async () => {
    const r = await opDiagnostics(root, { paths: [] });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.value).toEqual({ status: "ok", diagnostics: [] });
  });

  it("no tsconfig → unavailable shape", async () => {
    const r = await opDiagnostics(root, { paths: ["a.ts"] });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const v = r.value as DiagnosticsValue;
    expect(v.status).toBe("unavailable");
    expect(v.reason).toMatch(/tsconfig/);
    expect(v.diagnostics).toEqual([]);
  });

  it("non TS/JS paths → unavailable", async () => {
    await writeFile(
      join(dir, "tsconfig.json"),
      JSON.stringify({ compilerOptions: { strict: true }, include: ["*.ts"] }),
    );
    const r = await opDiagnostics(root, { paths: ["readme.md", "a.py"] });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const v = r.value as DiagnosticsValue;
    expect(v.status).toBe("unavailable");
    expect(v.reason).toMatch(/TypeScript|JavaScript/);
    expect(v.diagnostics).toEqual([]);
  });

  it("returns structured errors for a broken TS file", async () => {
    await writeFile(
      join(dir, "tsconfig.json"),
      JSON.stringify({
        compilerOptions: {
          strict: true,
          noEmit: true,
          target: "ES2020",
          module: "ESNext",
          skipLibCheck: true,
        },
        include: ["*.ts"],
      }),
    );
    await writeFile(
      join(dir, "broken.ts"),
      "const x: number = 'oops';\n consy y = missing;\n",
    );

    const r = await opDiagnostics(root, { paths: ["broken.ts"] });
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    const v = r.value as DiagnosticsValue;
    expect(v.status).toBe("ok");
    expect(v.diagnostics.length).toBeGreaterThan(0);
    expect(v.diagnostics.some((d) => d.severity === "error")).toBe(true);
    const first = v.diagnostics[0];
    expect(first.path).toBe("broken.ts");
    expect(first.line).toBeGreaterThanOrEqual(1);
    expect(first.column).toBeGreaterThanOrEqual(1);
    expect(first.message.length).toBeGreaterThan(0);
    expect(first.code).toMatch(/^TS\d+$/);
  });

  it("organize / readonly session roots allow diagnostics", () => {
    const organize: StoredRoot = {
      id: "o",
      name: "o",
      absPath: dir,
      sessionOnly: true,
      conversationId: "c1",
      mode: "organize",
    };
    const readonlyRoot: StoredRoot = {
      id: "r",
      name: "r",
      absPath: dir,
      sessionOnly: true,
      conversationId: "c1",
      mode: "readonly",
    };
    expect(
      sessionRootAccessError(organize, "diagnostics", { paths: [] }),
    ).toBeNull();
    expect(
      sessionRootAccessError(readonlyRoot, "diagnostics", { paths: [] }),
    ).toBeNull();
  });
});
