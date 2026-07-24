/**
 * 用户交互 shell IPC 契约（M3 · 右坞「你的终端」）—— 主进程 / preload / renderer 三端共享。
 *
 * 与 `process-contract.ts`（AI 后台进程）/ `terminal-contract.ts`（外置终端）并列，不混装。
 * spawn / input / resize / kill / list / read 走 invoke；输出增量经 `event` push。
 */

/** Pty 会话生命周期（与 ProcessStatus 同形，便于 process_list 融合）。 */
export type PtyStatus = "running" | "exited";

/** `pty:list` 单条。 */
export interface PtySessionItem {
  session_id: string;
  conversation_id: string;
  /** 显示名：用户终端 #N */
  name: string;
  /** shell 可执行名（如 powershell.exe / bash）。 */
  shell: string;
  /** 会话序号（对话内从 1 起，关闭后不复用）。 */
  index: number;
  status: PtyStatus;
  started_at: string;
  exit_code?: number | null;
}

export interface PtyListValue {
  sessions: PtySessionItem[];
}

/** `pty:read` 成功 value —— 原始 ANSI 环形 buffer（xterm 回放；不 strip）。 */
export interface PtyReadValue {
  session_id: string;
  status: PtyStatus;
  output: string;
  exit_code?: number | null;
}

/** spawn 成功 value。 */
export interface PtySpawnValue {
  session_id: string;
  item: PtySessionItem;
}

/** 主进程 → renderer 推送。 */
export type PtyEventPush =
  | {
      type: "data";
      session_id: string;
      conversation_id: string;
      chunk: string;
    }
  | {
      type: "started";
      session_id: string;
      conversation_id: string;
      item: PtySessionItem;
    }
  | {
      type: "exited";
      session_id: string;
      conversation_id: string;
      exit_code: number | null;
    };

export const PTY_CHANNELS = {
  spawn: "pty:spawn",
  input: "pty:input",
  resize: "pty:resize",
  kill: "pty:kill",
  list: "pty:list",
  read: "pty:read",
  killConversation: "pty:killConversation",
  event: "pty:event",
} as const;

export interface PtySpawnRequest {
  conversation_id: string;
  /** 本地 FS 根 id（主进程解析 abs cwd）。 */
  root_id: string;
  /** 工作区子路径（scratch）；空 = 根自身。 */
  subpath?: string;
}

export interface PtyInputRequest {
  session_id: string;
  data: string;
}

export interface PtyResizeRequest {
  session_id: string;
  cols: number;
  rows: number;
}

export interface PtyKillRequest {
  session_id: string;
}

export interface PtyListRequest {
  conversation_id: string;
}

export interface PtyReadRequest {
  session_id: string;
  /** 仅返回末尾 N 行（可选）。 */
  tail_lines?: number;
}

export interface PtyKillConversationRequest {
  conversation_id: string;
}

/** spawn / kill 等 invoke 的判别结果。 */
export type PtyResult<T> =
  | { ok: true; value: T }
  | { ok: false; error: { kind: string; detail: string } };

/** AI `process_stop` 拒停用户终端时的固定文案（契约层常量，供单测断言）。 */
export const PTY_STOP_REJECTED_DETAIL = "用户终端仅可由用户关闭，AI 不可停止";

/** AI `process_list` 中的显示名前缀。 */
export const PTY_PROCESS_NAME_PREFIX = "用户终端 #";

/** 暴露在 `window.ptyApi` 上的 renderer 端 API 面。 */
export interface PtyApi {
  spawn: (req: PtySpawnRequest) => Promise<PtyResult<PtySpawnValue>>;
  input: (req: PtyInputRequest) => Promise<PtyResult<void>>;
  resize: (req: PtyResizeRequest) => Promise<PtyResult<void>>;
  /** 用户关闭会话（主权）。 */
  kill: (req: PtyKillRequest) => Promise<PtyResult<PtySessionItem>>;
  list: (req: PtyListRequest) => Promise<PtyListValue>;
  /** 读当前环形 buffer（刷新 / 重挂载时 hydrate）。 */
  read: (req: PtyReadRequest) => Promise<PtyResult<PtyReadValue>>;
  killConversation: (req: PtyKillConversationRequest) => Promise<void>;
  onEvent: (cb: (e: PtyEventPush) => void) => () => void;
}
