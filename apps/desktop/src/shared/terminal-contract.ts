/**
 * 聊天代码块「在终端运行」IPC 契约 —— 主进程 / preload / renderer 三端共享。
 *
 * 仅桌面 Electron 外壳暴露；浏览器预览不注入。
 * 用户直触路径：renderer 先走聊天内 RunConfirm，再以
 * `{ command, rendererConfirmed: true }` 调用——主进程跳过 native OS 框。
 * 旧 string 入参仍走 native 兜底（兼容）。
 */

export const TERMINAL_CHANNELS = {
  runBash: "terminal:runBash",
  openShellAtRoot: "terminal:openShellAtRoot",
} as const;

export type TerminalRunResult = { ok: true } | { ok: false; reason: string };

/** `runBash` 入参：string（旧）或带 renderer 确认标记的对象。 */
export type TerminalRunBashInput =
  | string
  | { command: string; rendererConfirmed?: boolean };

/** 暴露在 `window.terminalApi` 上的 renderer 端 API 面。 */
export interface TerminalApi {
  /**
   * 在用户 shell 的新终端窗口中运行命令。
   * `rendererConfirmed: true` 或主进程本会话已放行时跳过 native 确认。
   */
  runBash: (input: TerminalRunBashInput) => Promise<TerminalRunResult>;
  /**
   * 在授权本地工作区目录打开交互式终端（无命令确认门；仅 cd 到工作区根）。
   * `subpath` 为容器根下的工作区子路径（对话级 scratch 对称化）。
   */
  openShellAtRoot: (
    rootId: string,
    subpath?: string,
  ) => Promise<TerminalRunResult>;
}
