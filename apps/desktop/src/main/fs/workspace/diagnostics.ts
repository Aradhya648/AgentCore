/**
 * 本地工作区 op ``diagnostics``：TypeScript LanguageService 语义/语法诊断（写码验证内环）。
 *
 * 成功信封恒为 ``ok:true``；能力不足时 ``value.status=unavailable`` + 中文 reason，禁止抛穿通道。
 * LanguageService 按 root 缓存，文件内容变更靠版本号 invalidate。
 */
import { existsSync, readFileSync, statSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join, relative, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { resolveLexical } from "../pathGuard";
import type { StoredRoot } from "../roots";
import { opOk, toPosix } from "./result";

/** 单次 op 墙钟上限（安全网，非主方案）。 */
export const DIAGNOSTICS_TIMEOUT_MS = 15_000;

const TS_JS_EXT = /\.(?:[cm]?[jt]sx?)$/i;

export type DiagnosticSeverity = "error" | "warning" | "info";

export interface DiagnosticItem {
  path: string;
  line: number;
  column: number;
  severity: DiagnosticSeverity;
  message: string;
  code?: string;
}

export interface DiagnosticsValue {
  status: "ok" | "unavailable";
  reason?: string;
  diagnostics: DiagnosticItem[];
}

/** TS DiagnosticCategory → wire severity；未知类别返回 null。 */
export function mapDiagnosticSeverity(
  category: number,
): DiagnosticSeverity | null {
  // typescript.DiagnosticCategory: Warning=0, Error=1, Suggestion=2, Message=3
  if (category === 1) return "error";
  if (category === 0) return "warning";
  if (category === 2 || category === 3) return "info";
  return null;
}

export function isTsJsPath(relPath: string): boolean {
  const base = relPath.replace(/\\/g, "/").split("/").pop() ?? "";
  return TS_JS_EXT.test(base);
}

export function unavailable(reason: string): DiagnosticsValue {
  return { status: "unavailable", reason, diagnostics: [] };
}

export function emptyOk(): DiagnosticsValue {
  return { status: "ok", diagnostics: [] };
}

/** 解析 args.paths；非法条目丢弃。 */
export function parsePathsArg(args: Record<string, unknown>): string[] {
  const raw = args.paths;
  if (!Array.isArray(raw)) return [];
  const out: string[] = [];
  for (const p of raw) {
    if (typeof p !== "string") continue;
    const t = p.trim();
    if (t) out.push(t.replace(/\\/g, "/"));
  }
  return out;
}

type TsModule = typeof import("typescript");

interface FileCacheEntry {
  version: string;
  content: string;
}

interface RootServiceCache {
  rootAbs: string;
  configPath: string;
  configMtimeMs: number;
  ts: TsModule;
  service: import("typescript").LanguageService;
  /** 可变：按需把请求文件挂进 program。 */
  scriptFileNames: string[];
  versions: Map<string, FileCacheEntry>;
  options: import("typescript").CompilerOptions;
}

const serviceByRoot = new Map<string, RootServiceCache>();

/** @internal test-only */
export function _clearDiagnosticsCacheForTests(): void {
  for (const c of serviceByRoot.values()) {
    c.service.dispose();
  }
  serviceByRoot.clear();
}

function tryLoadTypescript(rootAbs: string): TsModule | null {
  const workspaceEntry = join(rootAbs, "node_modules", "typescript");
  if (existsSync(workspaceEntry)) {
    try {
      const pkgJson = join(rootAbs, "package.json");
      const req = existsSync(pkgJson)
        ? createRequire(pkgJson)
        : createRequire(pathToFileURL(join(rootAbs, "x.js")).href);
      return req("typescript") as TsModule;
    } catch {
      try {
        const req = createRequire(pathToFileURL(join(rootAbs, "x.js")).href);
        return req(workspaceEntry) as TsModule;
      } catch {
        // fall through to bundled
      }
    }
  }
  try {
    const req = createRequire(import.meta.url);
    return req("typescript") as TsModule;
  } catch {
    try {
      return require("typescript") as TsModule;
    } catch {
      return null;
    }
  }
}

function findTsConfig(ts: TsModule, rootAbs: string): string | null {
  const found = ts.findConfigFile(
    rootAbs,
    (f) => ts.sys.fileExists(f),
    "tsconfig.json",
  );
  if (!found) return null;
  const rel = relative(rootAbs, found);
  if (!rel || rel.startsWith("..")) return null;
  return found;
}

function readConfig(
  ts: TsModule,
  rootAbs: string,
  configPath: string,
): {
  options: import("typescript").CompilerOptions;
  fileNames: string[];
} | null {
  const read = ts.readConfigFile(configPath, (p) => ts.sys.readFile(p));
  if (read.error) return null;
  const parsed = ts.parseJsonConfigFileContent(
    read.config,
    ts.sys,
    dirname(configPath),
  );
  if (!parsed.options) return null;
  const fileNames = parsed.fileNames.filter((f) => {
    const rel = relative(rootAbs, f);
    return Boolean(rel) && !rel.startsWith("..");
  });
  return { options: parsed.options, fileNames };
}

function normalizeScriptPath(abs: string): string {
  return resolve(abs);
}

function acquireService(
  rootAbs: string,
  ts: TsModule,
  configPath: string,
): RootServiceCache | null {
  let configMtimeMs = 0;
  try {
    configMtimeMs = statSync(configPath).mtimeMs;
  } catch {
    return null;
  }

  const existing = serviceByRoot.get(rootAbs);
  if (
    existing &&
    existing.configPath === configPath &&
    existing.configMtimeMs === configMtimeMs
  ) {
    return existing;
  }

  if (existing) {
    existing.service.dispose();
    serviceByRoot.delete(rootAbs);
  }

  const cfg = readConfig(ts, rootAbs, configPath);
  if (!cfg) return null;

  const versions = new Map<string, FileCacheEntry>();
  const scriptFileNames = cfg.fileNames.map(normalizeScriptPath);

  const host: import("typescript").LanguageServiceHost = {
    getCompilationSettings: () => cfg.options,
    getScriptFileNames: () => scriptFileNames.slice(),
    getScriptVersion: (fileName) =>
      versions.get(normalizeScriptPath(fileName))?.version ?? "0",
    getScriptSnapshot: (fileName) => {
      const key = normalizeScriptPath(fileName);
      let entry = versions.get(key);
      if (!entry) {
        const content = ts.sys.readFile(key);
        if (content === undefined) return undefined;
        entry = { version: "1", content };
        versions.set(key, entry);
      }
      return ts.ScriptSnapshot.fromString(entry.content);
    },
    getCurrentDirectory: () => rootAbs,
    getDefaultLibFileName: (opts) => ts.getDefaultLibFilePath(opts),
    fileExists: (f) => ts.sys.fileExists(f),
    readFile: (f) => ts.sys.readFile(f),
    readDirectory: ts.sys.readDirectory,
    directoryExists: ts.sys.directoryExists,
    getDirectories: ts.sys.getDirectories,
  };

  const cache: RootServiceCache = {
    rootAbs,
    configPath,
    configMtimeMs,
    ts,
    service: ts.createLanguageService(host, ts.createDocumentRegistry()),
    scriptFileNames,
    versions,
    options: cfg.options,
  };
  serviceByRoot.set(rootAbs, cache);
  return cache;
}

function touchScriptFile(
  cache: RootServiceCache,
  absPath: string,
): string | null {
  const key = normalizeScriptPath(absPath);
  try {
    const content = readFileSync(key, "utf-8");
    const prev = cache.versions.get(key);
    if (!prev || prev.content !== content) {
      const nextVer = prev ? String(Number(prev.version) + 1) : "1";
      cache.versions.set(key, { version: nextVer, content });
    }
    if (!cache.scriptFileNames.includes(key)) {
      cache.scriptFileNames.push(key);
    }
    return key;
  } catch {
    return null;
  }
}

export function toWireDiagnostic(
  ts: TsModule,
  rootAbs: string,
  d: import("typescript").Diagnostic,
): DiagnosticItem | null {
  const severity = mapDiagnosticSeverity(d.category);
  // error 必须；warning 可含以省实现分支；info/suggestion 省略以省上下文
  if (severity !== "error" && severity !== "warning") return null;

  let fileRel = "";
  let line = 1;
  let column = 1;
  if (d.file && typeof d.start === "number") {
    const abs = normalizeScriptPath(d.file.fileName);
    fileRel = toPosix(relative(rootAbs, abs));
    const pos = d.file.getLineAndCharacterOfPosition(d.start);
    line = pos.line + 1;
    column = pos.character + 1;
  }

  const message = ts.flattenDiagnosticMessageText(d.messageText, "\n");
  const item: DiagnosticItem = {
    path: fileRel,
    line,
    column,
    severity,
    message,
  };
  if (typeof d.code === "number") {
    item.code = `TS${d.code}`;
  }
  return item;
}

function collectForPaths(
  cache: RootServiceCache,
  rootAbs: string,
  absPaths: string[],
  deadline: number,
): DiagnosticsValue {
  const { ts, service } = cache;
  const out: DiagnosticItem[] = [];
  const seen = new Set<string>();

  for (const abs of absPaths) {
    if (Date.now() > deadline) {
      return unavailable("诊断超时");
    }
    const key = touchScriptFile(cache, abs);
    if (!key) continue;

    const diags = [
      ...service.getSyntacticDiagnostics(key),
      ...service.getSemanticDiagnostics(key),
    ];
    for (const d of diags) {
      if (Date.now() > deadline) {
        return unavailable("诊断超时");
      }
      if (
        d.category !== ts.DiagnosticCategory.Error &&
        d.category !== ts.DiagnosticCategory.Warning
      ) {
        continue;
      }
      const item = toWireDiagnostic(ts, rootAbs, d);
      if (!item) continue;
      const sig = `${item.path}:${item.line}:${item.column}:${item.code ?? ""}:${item.message}`;
      if (seen.has(sig)) continue;
      seen.add(sig);
      out.push(item);
    }
  }

  return { status: "ok", diagnostics: out };
}

function runDiagnosticsSync(
  root: StoredRoot,
  paths: string[],
  deadline: number,
): DiagnosticsValue {
  if (paths.length === 0) return emptyOk();

  const tsJsPaths = paths.filter(isTsJsPath);
  if (tsJsPaths.length === 0) {
    return unavailable("仅支持 TypeScript/JavaScript 文件");
  }

  const rootAbs = resolve(root.absPath);
  const ts = tryLoadTypescript(rootAbs);
  if (!ts) {
    return unavailable("未安装 TypeScript 语言服务");
  }

  const configPath = findTsConfig(ts, rootAbs);
  if (!configPath) {
    return unavailable("工作区未找到 tsconfig.json");
  }

  const cache = acquireService(rootAbs, ts, configPath);
  if (!cache) {
    return unavailable("无法解析 tsconfig.json");
  }

  const absPaths: string[] = [];
  for (const rel of tsJsPaths) {
    if (Date.now() > deadline) return unavailable("诊断超时");
    const abs = resolveLexical(root, rel);
    if (!abs) continue;
    absPaths.push(abs);
  }

  if (absPaths.length === 0) {
    return unavailable("路径无效或越出工作区");
  }

  return collectForPaths(cache, rootAbs, absPaths, deadline);
}

/**
 * 工作区 op ``diagnostics``。
 * args: ``{ paths: string[] }``（工作区相对 POSIX 路径）。
 */
export async function opDiagnostics(
  root: StoredRoot,
  args: Record<string, unknown>,
): Promise<WorkspaceOpResult> {
  const paths = parsePathsArg(args);
  const deadline = Date.now() + DIAGNOSTICS_TIMEOUT_MS;

  let timer: ReturnType<typeof setTimeout> | undefined;
  try {
    const value = await Promise.race([
      Promise.resolve().then(() => runDiagnosticsSync(root, paths, deadline)),
      new Promise<DiagnosticsValue>((resolvePromise) => {
        timer = setTimeout(
          () => resolvePromise(unavailable("诊断超时")),
          DIAGNOSTICS_TIMEOUT_MS,
        );
      }),
    ]);
    return opOk(value);
  } catch (e) {
    const msg = e instanceof Error ? e.message : String(e);
    return opOk(unavailable(`诊断失败：${msg}`));
  } finally {
    if (timer !== undefined) clearTimeout(timer);
  }
}
