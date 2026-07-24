import { notifyActionError, notifyError, notifyInfo } from "@/lib/toast";
import { useRunConfirmStore } from "@/stores/runConfirm";
import type { TerminalRunResult } from "@shared/terminal-contract";

/** Surface `terminalApi` outcomes — cancel is info, failure is error. */
export function handleTerminalResult(
  result: TerminalRunResult,
  opts?: { cancelMessage?: string },
): void {
  if (result.ok) return;
  if (result.reason === "已取消") {
    notifyInfo(opts?.cancelMessage ?? "已取消");
    return;
  }
  notifyError(result.reason);
}

/**
 * 用户直触 bash：先走聊天内 RunConfirm，再以 `rendererConfirmed` 调主进程
 *（跳过 native OS 框）。已「本会话都允许」则直跑。
 */
export async function runTerminalBash(command: string): Promise<void> {
  const api = window.terminalApi;
  if (!api?.runBash) {
    notifyError("终端不可用（非桌面环境）");
    return;
  }

  const decision = await useRunConfirmStore
    .getState()
    .requestRunConfirm(command);
  if (decision === "cancel") {
    notifyInfo("已取消在终端运行");
    return;
  }

  try {
    const result = await api.runBash({
      command,
      rendererConfirmed: true,
    });
    handleTerminalResult(result, { cancelMessage: "已取消在终端运行" });
  } catch (e) {
    notifyActionError("无法在终端运行", e);
  }
}
