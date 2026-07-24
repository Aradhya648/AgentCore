/**
 * 后台进程 IPC 契约（终端 tab / workspace process_* op）—— 主进程 / preload / renderer 三端共享。
 *
 * 与 `terminal-contract.ts`（外置终端「在终端运行」）并列，不混装。
 * 列表 / 停止走 invoke；输出增量经 `event` push（仿 sidecar:event）。
 */

/** 进程生命周期状态。 */
export type ProcessStatus = "running" | "exited";

/** `process_start` / `process_read` / `process_stop` 成功 value 同形。 */
export interface ProcessOpValue {
  process_id: string;
  status: ProcessStatus;
  /** 累计输出（环形 buffer 全文，或 wait 期间捕获段）。 */
  output: string;
  /** `wait_for` 是否命中；未请求 wait 时省略。 */
  matched?: boolean;
  exit_code?: number | null;
}

/** `process_list` 单条。 */
export interface ProcessListItem {
  process_id: string;
  name?: string;
  command: string;
  status: ProcessStatus;
  /** ISO-8601 或 epoch ms 字符串均可；桌面主进程用 ISO。 */
  started_at: string;
  exit_code?: number | null;
}

export interface ProcessListValue {
  processes: ProcessListItem[];
}

/** 主进程 → renderer 推送。 */
export type ProcessEventPush =
  | {
      type: "output";
      process_id: string;
      conversation_id: string;
      chunk: string;
    }
  | {
      type: "started";
      process_id: string;
      conversation_id: string;
      item: ProcessListItem;
    }
  | {
      type: "exited";
      process_id: string;
      conversation_id: string;
      exit_code: number | null;
    };

export const PROCESS_CHANNELS = {
  list: "process:list",
  stop: "process:stop",
  read: "process:read",
  killConversation: "process:killConversation",
  event: "process:event",
} as const;

export interface ProcessListRequest {
  conversation_id: string;
}

export interface ProcessStopRequest {
  process_id: string;
}

export interface ProcessReadRequest {
  process_id: string;
  /** 仅返回末尾 N 行（可选）。 */
  tail_lines?: number;
}

export interface ProcessKillConversationRequest {
  conversation_id: string;
}

/** 暴露在 `window.processApi` 上的 renderer 端 API 面。 */
export interface ProcessApi {
  /** 列本对话进程（含已退出、仍记账的）。 */
  list: (req: ProcessListRequest) => Promise<ProcessListValue>;
  /** 用户停止（主权、不走审批）。 */
  stop: (req: ProcessStopRequest) => Promise<ProcessOpValue>;
  /** 读当前环形 buffer（选中进程时 hydrate）。 */
  read: (req: ProcessReadRequest) => Promise<ProcessOpValue>;
  /** 对话删除时终止并清账。 */
  killConversation: (req: ProcessKillConversationRequest) => Promise<void>;
  /** 订阅输出增量 / 启停事件；返回取消订阅。 */
  onEvent: (cb: (e: ProcessEventPush) => void) => () => void;
}
