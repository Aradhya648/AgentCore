import { randomUUID } from "node:crypto";
/**
 * 用户交互 shell 服务 —— node-pty 会话、环形输出 buffer、按 conversation_id 记账。
 *
 * 与 `process-service.ts`（AI 后台进程）/ `terminal-service.ts`（外置终端）并列，不混装。
 * 应用退出 / 删对话一律终止（与 process-service 同姿态）。
 */
import { basename } from "node:path";
import type { ProcessListItem, ProcessOpValue } from "@shared/process-contract";
import {
  PTY_CHANNELS,
  PTY_PROCESS_NAME_PREFIX,
  PTY_STOP_REJECTED_DETAIL,
  type PtyEventPush,
  type PtyListValue,
  type PtyReadValue,
  type PtyResult,
  type PtySessionItem,
  type PtySpawnValue,
  type PtyStatus,
} from "@shared/pty-contract";
import { BrowserWindow, app, ipcMain } from "electron";
import { getStoredRoot } from "./fs-service";
import { resolveCwdInside } from "./fs/pathGuard";
import { isRecord, requireStringFields } from "./ipc-validate";

/** 单会话环形输出上限（约 1MB）。 */
export const PTY_BUFFER_CAP = 1024 * 1024;

/** 单对话交互 shell 上限。 */
export const PTY_CONCURRENCY_CAP = 3;

/** AI `process_stop` 拒停时的 typed 错误 kind。 */
export const PTY_STOP_REJECTED_KIND = "WorkspaceIOError";

type PtyHandle = {
  write: (data: string) => void;
  resize: (cols: number, rows: number) => void;
  kill: () => void;
  onData: (cb: (data: string) => void) => void;
  onExit: (cb: (e: { exitCode: number }) => void) => void;
};

export interface PtyRecord {
  session_id: string;
  conversation_id: string;
  index: number;
  name: string;
  shell: string;
  cwd: string;
  status: PtyStatus;
  started_at: string;
  exit_code: number | null;
  buffer: string;
  pty: PtyHandle | null;
}

/** 环形截断：超长时丢弃头部，保留尾部 cap 字节（UTF-16 码元近似）。 */
export function appendRingBuffer(
  current: string,
  chunk: string,
  cap = PTY_BUFFER_CAP,
): string {
  if (!chunk) return current;
  const next = current + chunk;
  if (next.length <= cap) return next;
  return next.slice(next.length - cap);
}

/** 取末尾 N 行（N≤0 或非有限 → 全文）。 */
export function tailLines(text: string, n?: number): string {
  if (n == null || !Number.isFinite(n) || n <= 0) return text;
  const lines = text.split("\n");
  if (lines.length <= n) return text;
  return lines.slice(-n).join("\n");
}

/** Strip CSI / OSC 等常见 ESC 序列（供 AI process_read）。 */
export function stripAnsi(text: string): string {
  const ESC = String.fromCharCode(0x1b);
  const BEL = String.fromCharCode(0x07);
  const re = new RegExp(
    `${ESC}(?:[@-Z\\\\-_]|\\[[0-?]*[ -/]*[@-~]|\\][^${BEL}]*(?:${BEL}|${ESC}\\\\))`,
    "g",
  );
  return text.replace(re, "");
}

/**
 * Win 启动时关掉 PSReadLine 可听响铃（默认 Audible → Console.Beep，右坞内嵌终端会「咕」一声）。
 * `-NoExit` 保证 -Command 执行完仍落交互提示符；try/catch 兼容无 PSReadLine 的精简环境。
 */
export const WIN_PS_MUTE_BELL_COMMAND =
  "try { Set-PSReadLineOption -BellStyle None } catch {}";

/** 解析默认 shell：Win → powershell.exe（回落 ComSpec）；POSIX → $SHELL（回落 /bin/sh）。 */
export function resolveDefaultShell(
  platform: NodeJS.Platform = process.platform,
  env: NodeJS.ProcessEnv = process.env,
): { file: string; args: string[] } {
  if (platform === "win32") {
    const ps = "powershell.exe";
    // Prefer PowerShell; ComSpec is typically cmd.exe as fallback when PS missing at spawn.
    return {
      file: ps,
      args: ["-NoLogo", "-NoExit", "-Command", WIN_PS_MUTE_BELL_COMMAND],
    };
  }
  const shell = (env.SHELL || "").trim() || "/bin/sh";
  return { file: shell, args: [] };
}

export function shellDisplayName(file: string): string {
  return basename(file) || file;
}

function broadcast(event: PtyEventPush): void {
  for (const win of BrowserWindow.getAllWindows()) {
    if (!win.isDestroyed()) {
      win.webContents.send(PTY_CHANNELS.event, event);
    }
  }
}

function toItem(rec: PtyRecord): PtySessionItem {
  return {
    session_id: rec.session_id,
    conversation_id: rec.conversation_id,
    name: rec.name,
    shell: rec.shell,
    index: rec.index,
    status: rec.status,
    started_at: rec.started_at,
    exit_code: rec.exit_code ?? undefined,
  };
}

/** 导出给 process_list 融合。 */
export function toProcessListItem(rec: PtyRecord): ProcessListItem {
  return {
    process_id: rec.session_id,
    name: rec.name,
    command: rec.shell,
    status: rec.status,
    started_at: rec.started_at,
    exit_code: rec.exit_code ?? undefined,
  };
}

function toProcessOpValue(rec: PtyRecord, output: string): ProcessOpValue {
  return {
    process_id: rec.session_id,
    status: rec.status,
    output,
    ...(rec.exit_code !== null ? { exit_code: rec.exit_code } : {}),
  };
}

/** 惰性加载 node-pty（单测可注入 mock）。 */
let spawnPtyImpl: (
  file: string,
  args: string[],
  opts: {
    name: string;
    cols: number;
    rows: number;
    cwd: string;
    env: NodeJS.ProcessEnv;
  },
) => PtyHandle = (file, args, opts) => {
  // eslint-disable-next-line @typescript-eslint/no-require-imports
  const nodePty = require("node-pty") as {
    spawn: (
      f: string,
      a: string[] | string,
      o: Record<string, unknown>,
    ) => {
      write: (d: string) => void;
      resize: (c: number, r: number) => void;
      kill: () => void;
      onData: (cb: (d: string) => void) => void;
      onExit: (cb: (e: { exitCode: number }) => void) => void;
    };
  };
  return nodePty.spawn(file, args, {
    name: opts.name,
    cols: opts.cols,
    rows: opts.rows,
    cwd: opts.cwd,
    env: opts.env,
  });
};

/** 测试注入。 */
export function setPtySpawnerForTests(fn: typeof spawnPtyImpl | null): void {
  if (fn) {
    spawnPtyImpl = fn;
  } else {
    spawnPtyImpl = (file, args, opts) => {
      // eslint-disable-next-line @typescript-eslint/no-require-imports
      const nodePty = require("node-pty") as {
        spawn: (
          f: string,
          a: string[] | string,
          o: Record<string, unknown>,
        ) => PtyHandle;
      };
      return nodePty.spawn(file, args, opts);
    };
  }
}

class PtyService {
  private readonly byId = new Map<string, PtyRecord>();
  /** 对话内序号计数器（只增不复用）。 */
  private readonly nextIndex = new Map<string, number>();

  runningCount(conversationId: string): number {
    let n = 0;
    for (const r of this.byId.values()) {
      if (r.conversation_id === conversationId && r.status === "running") n++;
    }
    return n;
  }

  get(sessionId: string): PtyRecord | undefined {
    return this.byId.get(sessionId);
  }

  isUserTerminal(id: string): boolean {
    return this.byId.has(id);
  }

  list(conversationId: string): PtyListValue {
    const sessions: PtySessionItem[] = [];
    for (const r of this.byId.values()) {
      if (r.conversation_id === conversationId) sessions.push(toItem(r));
    }
    sessions.sort((a, b) => a.index - b.index);
    return { sessions };
  }

  /** 供 workspace `process_list` 融合。 */
  listAsProcessItems(conversationId: string): ProcessListItem[] {
    const items: ProcessListItem[] = [];
    for (const r of this.byId.values()) {
      if (r.conversation_id === conversationId)
        items.push(toProcessListItem(r));
    }
    items.sort((a, b) => a.started_at.localeCompare(b.started_at));
    return items;
  }

  spawn(args: {
    conversation_id: string;
    cwd: string;
    cols?: number;
    rows?: number;
  }): PtyResult<PtySpawnValue> {
    const conversationId = args.conversation_id.trim();
    if (!conversationId) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "缺少 conversation_id" },
      };
    }
    if (!args.cwd.trim()) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "缺少工作区路径" },
      };
    }
    if (this.runningCount(conversationId) >= PTY_CONCURRENCY_CAP) {
      return {
        ok: false,
        error: {
          kind: "WorkspaceIOError",
          detail: `本对话用户终端已达上限（${PTY_CONCURRENCY_CAP}）`,
        },
      };
    }

    const index = (this.nextIndex.get(conversationId) ?? 0) + 1;
    this.nextIndex.set(conversationId, index);
    const sessionId = randomUUID();
    const { file, args: shellArgs } = resolveDefaultShell();
    const shellName = shellDisplayName(file);
    const name = `${PTY_PROCESS_NAME_PREFIX}${index}`;

    const rec: PtyRecord = {
      session_id: sessionId,
      conversation_id: conversationId,
      index,
      name,
      shell: shellName,
      cwd: args.cwd,
      status: "running",
      started_at: new Date().toISOString(),
      exit_code: null,
      buffer: "",
      pty: null,
    };
    this.byId.set(sessionId, rec);

    let handle: PtyHandle;
    try {
      handle = spawnPtyImpl(file, shellArgs, {
        name: "xterm-256color",
        cols: args.cols && args.cols > 0 ? args.cols : 80,
        rows: args.rows && args.rows > 0 ? args.rows : 24,
        cwd: args.cwd,
        env: process.env,
      });
    } catch (e) {
      // Windows：powershell 缺失时回落 ComSpec
      if (process.platform === "win32") {
        const fallback = process.env.ComSpec || "cmd.exe";
        try {
          handle = spawnPtyImpl(fallback, [], {
            name: "xterm-256color",
            cols: args.cols && args.cols > 0 ? args.cols : 80,
            rows: args.rows && args.rows > 0 ? args.rows : 24,
            cwd: args.cwd,
            env: process.env,
          });
          rec.shell = shellDisplayName(fallback);
        } catch (e2) {
          this.byId.delete(sessionId);
          return {
            ok: false,
            error: {
              kind: "WorkspaceIOError",
              detail: `无法启动 shell：${e2 instanceof Error ? e2.message : String(e2)}`,
            },
          };
        }
      } else {
        this.byId.delete(sessionId);
        return {
          ok: false,
          error: {
            kind: "WorkspaceIOError",
            detail: `无法启动 shell：${e instanceof Error ? e.message : String(e)}`,
          },
        };
      }
    }
    rec.pty = handle;

    handle.onData((chunk) => {
      rec.buffer = appendRingBuffer(rec.buffer, chunk);
      broadcast({
        type: "data",
        session_id: sessionId,
        conversation_id: conversationId,
        chunk,
      });
    });

    handle.onExit(({ exitCode }) => {
      if (rec.status === "exited") return;
      rec.status = "exited";
      rec.exit_code = exitCode ?? 0;
      rec.pty = null;
      broadcast({
        type: "exited",
        session_id: sessionId,
        conversation_id: conversationId,
        exit_code: rec.exit_code,
      });
    });

    broadcast({
      type: "started",
      session_id: sessionId,
      conversation_id: conversationId,
      item: toItem(rec),
    });

    return { ok: true, value: { session_id: sessionId, item: toItem(rec) } };
  }

  input(sessionId: string, data: string): PtyResult<void> {
    const rec = this.byId.get(sessionId);
    if (!rec || rec.status !== "running" || !rec.pty) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "会话不存在或已退出" },
      };
    }
    try {
      rec.pty.write(data);
      return { ok: true, value: undefined };
    } catch (e) {
      return {
        ok: false,
        error: {
          kind: "WorkspaceIOError",
          detail: e instanceof Error ? e.message : String(e),
        },
      };
    }
  }

  resize(sessionId: string, cols: number, rows: number): PtyResult<void> {
    const rec = this.byId.get(sessionId);
    if (!rec || rec.status !== "running" || !rec.pty) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "会话不存在或已退出" },
      };
    }
    if (
      !Number.isFinite(cols) ||
      !Number.isFinite(rows) ||
      cols < 1 ||
      rows < 1
    ) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "无效的 cols/rows" },
      };
    }
    try {
      rec.pty.resize(Math.floor(cols), Math.floor(rows));
      return { ok: true, value: undefined };
    } catch (e) {
      return {
        ok: false,
        error: {
          kind: "WorkspaceIOError",
          detail: e instanceof Error ? e.message : String(e),
        },
      };
    }
  }

  /** 用户关闭会话（从记账中移除）。 */
  kill(sessionId: string): PtyResult<PtySessionItem> {
    const rec = this.byId.get(sessionId);
    if (!rec) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "会话不存在或已清理" },
      };
    }
    if (rec.status === "running" && rec.pty) {
      try {
        rec.pty.kill();
      } catch {
        /* already dead */
      }
      if (rec.status === "running") {
        rec.status = "exited";
        rec.exit_code = rec.exit_code ?? -1;
        rec.pty = null;
        broadcast({
          type: "exited",
          session_id: rec.session_id,
          conversation_id: rec.conversation_id,
          exit_code: rec.exit_code,
        });
      }
    }
    const item = toItem(rec);
    this.byId.delete(sessionId);
    return { ok: true, value: item };
  }

  /**
   * AI `process_stop` 入口：用户终端一律拒绝。
   * @returns null 若非用户终端；否则 typed 错误结果。
   */
  rejectStopIfUserTerminal(processId: string): PtyResult<never> | null {
    if (!this.byId.has(processId)) return null;
    return {
      ok: false,
      error: {
        kind: PTY_STOP_REJECTED_KIND,
        detail: PTY_STOP_REJECTED_DETAIL,
      },
    };
  }

  /** AI `process_read`：strip ANSI 后返回。 */
  readAsProcess(processId: string, tail_lines?: number): ProcessOpValue | null {
    const rec = this.byId.get(processId);
    if (!rec) return null;
    const raw = tailLines(rec.buffer, tail_lines);
    return toProcessOpValue(rec, stripAnsi(raw));
  }

  /** 用户终端 hydrate：保留原始 ANSI（xterm 回放）。 */
  read(sessionId: string, tail_lines?: number): PtyResult<PtyReadValue> {
    const rec = this.byId.get(sessionId);
    if (!rec) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "会话不存在或已清理" },
      };
    }
    return {
      ok: true,
      value: {
        session_id: rec.session_id,
        status: rec.status,
        output: tailLines(rec.buffer, tail_lines),
        ...(rec.exit_code !== null ? { exit_code: rec.exit_code } : {}),
      },
    };
  }

  killConversation(conversationId: string): void {
    const ids: string[] = [];
    for (const r of this.byId.values()) {
      if (r.conversation_id === conversationId) ids.push(r.session_id);
    }
    for (const id of ids) {
      this.kill(id);
      this.byId.delete(id);
    }
    this.nextIndex.delete(conversationId);
  }

  killAll(): void {
    for (const id of [...this.byId.keys()]) {
      this.kill(id);
    }
    this.byId.clear();
    this.nextIndex.clear();
  }
}

/** 模块级单例 —— workspace op 与 IPC 共用。 */
export const ptyService = new PtyService();

/** 解析 spawn cwd：rootId + 可选 subpath（词法 + realpath 双守卫）。 */
export async function resolvePtyCwd(
  rootId: string,
  subpath = "",
): Promise<{ ok: true; cwd: string } | { ok: false; detail: string }> {
  const root = await getStoredRoot(rootId);
  if (!root) return { ok: false, detail: "本地目录未授权或已移除" };
  const rel = (subpath || ".").replace(/^\/+|\/+$/g, "") || ".";
  return resolveCwdInside(root, rel === "" || rel === "." ? undefined : rel);
}

let quitHooked = false;

export function registerPtyIpc(): void {
  ipcMain.handle(PTY_CHANNELS.spawn, async (_e, p: unknown) => {
    const args = requireStringFields(p, ["conversation_id", "root_id"]);
    if (!args) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "无效参数" },
      } satisfies PtyResult<PtySpawnValue>;
    }
    const subpath =
      isRecord(p) && typeof p.subpath === "string" ? p.subpath : "";
    const cwdRes = await resolvePtyCwd(args.root_id, subpath);
    if (!cwdRes.ok) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: cwdRes.detail },
      } satisfies PtyResult<PtySpawnValue>;
    }
    return ptyService.spawn({
      conversation_id: args.conversation_id,
      cwd: cwdRes.cwd,
    });
  });

  ipcMain.handle(PTY_CHANNELS.input, (_e, p: unknown) => {
    const args = requireStringFields(p, ["session_id"]);
    if (!args || !isRecord(p) || typeof p.data !== "string") {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "无效参数" },
      } satisfies PtyResult<void>;
    }
    return ptyService.input(args.session_id, p.data);
  });

  ipcMain.handle(PTY_CHANNELS.resize, (_e, p: unknown) => {
    const args = requireStringFields(p, ["session_id"]);
    if (!args || !isRecord(p)) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "无效参数" },
      } satisfies PtyResult<void>;
    }
    const cols = Number(p.cols);
    const rows = Number(p.rows);
    return ptyService.resize(args.session_id, cols, rows);
  });

  ipcMain.handle(PTY_CHANNELS.kill, (_e, p: unknown) => {
    const args = requireStringFields(p, ["session_id"]);
    if (!args) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "无效参数" },
      };
    }
    return ptyService.kill(args.session_id);
  });

  ipcMain.handle(PTY_CHANNELS.list, (_e, p: unknown) => {
    const args = requireStringFields(p, ["conversation_id"]);
    if (!args) return { sessions: [] };
    return ptyService.list(args.conversation_id);
  });

  ipcMain.handle(PTY_CHANNELS.read, (_e, p: unknown) => {
    const args = requireStringFields(p, ["session_id"]);
    if (!args) {
      return {
        ok: false,
        error: { kind: "WorkspaceIOError", detail: "无效参数" },
      } satisfies PtyResult<PtyReadValue>;
    }
    const tail =
      isRecord(p) && "tail_lines" in p ? Number(p.tail_lines) : undefined;
    return ptyService.read(
      args.session_id,
      Number.isFinite(tail) ? tail : undefined,
    );
  });

  ipcMain.handle(PTY_CHANNELS.killConversation, (_e, p: unknown) => {
    const args = requireStringFields(p, ["conversation_id"]);
    if (!args) return;
    ptyService.killConversation(args.conversation_id);
  });

  if (!quitHooked) {
    quitHooked = true;
    app.on("before-quit", () => {
      ptyService.killAll();
    });
  }
}
