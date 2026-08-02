/**
 * 回合停止生命周期（键 = conversationId，与 abort 注册同槽）。
 *
 * idle → preflight → streaming → stopping → stopped|completed|failed
 *
 * AbortSignal 只负责物理断流；是否允许开流 / 是否接受内容事件以本 phase 为准。
 *
 * 本文件保持**纯函数**（无 store 依赖），避免与 `store.ts` 循环引用。
 * 读写 phase 的命令式 API 见 `turnPhaseActions.ts`。
 */

export type TurnPhase =
  | "idle"
  | "preflight"
  | "streaming"
  | "stopping"
  | "stopped"
  | "completed"
  | "failed";

export type TurnTerminalOutcome = "stopped" | "completed" | "failed";

export function isTerminalPhase(phase: TurnPhase): boolean {
  return phase === "stopped" || phase === "completed" || phase === "failed";
}

/** stopping / terminal：禁止新开流（探活恢复点、sidecar invoke、云 fetch）。 */
export function blocksStreamOpen(phase: TurnPhase): boolean {
  return phase === "stopping" || isTerminalPhase(phase);
}

/** 仅 streaming 允许重建气泡、追加正文/工具等流式突变。 */
export function allowsStreamingMutations(phase: TurnPhase): boolean {
  return phase === "streaming";
}

/**
 * stopping：诚实过渡态——继续消费 run_*（含级联终态帧），正文/工具突变仍挡；
 * 仅后端 message_end/error 才定格。terminal：放行下一回合 message_start + 无害 meta。
 *
 * terminal 也放行 run_*：对齐云端 / sidecar D1——`message_end` 后 sink 仍可为 live
 * detached drive 续推 `run_completed` / `run_tool_progress`（conformance
 * `async_delivery`：detached → message_end → run_completed → execution_completed）。
 * 若挡掉，协作图会冻在收口前快照，直到（若有）execution_completed 刷新。
 */
export function allowsSseEvent(phase: TurnPhase, eventType: string): boolean {
  if (phase === "idle" || phase === "preflight" || phase === "streaming") {
    return true;
  }
  // terminal：放行下一回合 message_start（跨回合 preview 回放 / 同连接连续回合）。
  if (eventType === "message_start" && isTerminalPhase(phase)) {
    return true;
  }
  // stopping + terminal：run_* 必须入折（停止级联 / 异步团队后台帧）。
  if (
    (phase === "stopping" || isTerminalPhase(phase)) &&
    eventType.startsWith("run_")
  ) {
    return true;
  }
  return (
    eventType === "message_end" ||
    eventType === "error" ||
    eventType === "turn_saved" ||
    eventType === "title_generated" ||
    eventType === "followups_generated" ||
    eventType === "followups_unavailable" ||
    eventType === "citations" ||
    eventType === "evidence_ledger" ||
    // 排队按项取消：Stop 过程中仍可清 UI（Stop ≠ 取消排队，但 cancel 事件须入折）。
    eventType === "turn_queue_cancelled" ||
    // 异步团队：detached 可落在 message_end 前后；completed 常在 terminal 后同连接到达。
    eventType === "execution_detached" ||
    eventType === "execution_completed"
  );
}
