import { create } from "zustand";

/**
 * 用户直触 bash（代码块「在终端运行」）的聊天内确认门。
 *
 * 对标 Cursor：确认面在聊天内，不叠 OS 模态。三按钮决策后由
 * {@link import("@/lib/terminalFeedback").runTerminalBash} 以 `rendererConfirmed`
 * 调主进程；「本会话都允许」同时经 `fsApi.grantSessionRun` 置主进程 flag。
 */

export type RunConfirmDecision = "run" | "allow_session" | "cancel";

interface RunConfirmState {
  /** 当前待确认命令；null = 无卡。 */
  pending: { command: string } | null;
  /** renderer 侧本会话放行缓存（与主进程 flag 同步；进程重启清零）。 */
  sessionAllowed: boolean;
  /**
   * 请求用户确认。已 session 放行则立即 resolve `"run"`；
   * 若已有待确认项，先以 cancel 结算旧项再挂新卡。
   */
  requestRunConfirm: (command: string) => Promise<RunConfirmDecision>;
  /** 卡片按钮结算。 */
  decide: (decision: RunConfirmDecision) => void;
  /** 「本会话都允许」后本地置位（IPC grant 成功后调用）。 */
  markSessionAllowed: () => void;
  /** 测试用：清零。 */
  reset: () => void;
}

let pendingResolve: ((d: RunConfirmDecision) => void) | null = null;

export const useRunConfirmStore = create<RunConfirmState>((set, get) => ({
  pending: null,
  sessionAllowed: false,

  requestRunConfirm: (command) => {
    const trimmed = command.trim();
    if (!trimmed) return Promise.resolve("cancel");
    if (get().sessionAllowed) return Promise.resolve("run");

    if (pendingResolve) {
      pendingResolve("cancel");
      pendingResolve = null;
    }
    return new Promise((resolve) => {
      pendingResolve = resolve;
      set({ pending: { command: trimmed } });
    });
  },

  decide: (decision) => {
    const resolve = pendingResolve;
    pendingResolve = null;
    set({ pending: null });
    resolve?.(decision);
  },

  markSessionAllowed: () => set({ sessionAllowed: true }),

  reset: () => {
    if (pendingResolve) {
      pendingResolve("cancel");
      pendingResolve = null;
    }
    set({ pending: null, sessionAllowed: false });
  },
}));
