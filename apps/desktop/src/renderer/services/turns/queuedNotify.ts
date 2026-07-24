import { notifyInfo } from "@/lib/toast";

/** 排队态 toast（发送即有流 · ``turn_queued`` / 历史 midFlight 文案）。 */
export function notifyTurnQueued(position: number, queueDepth: number): void {
  notifyInfo(
    queueDepth > 1
      ? `已排队（第 ${position}/${queueDepth} 条），当前回合结束后处理`
      : "已排队，当前回合结束后处理",
  );
}
