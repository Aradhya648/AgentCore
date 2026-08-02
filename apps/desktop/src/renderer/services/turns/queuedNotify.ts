import { notifyInfo } from "@/lib/toast";

/** 排队态 toast（发送即有流 · ``turn_queued`` / 历史 midFlight 文案）。 */
export function notifyTurnQueued(position: number, queueDepth: number): void {
  notifyInfo(
    queueDepth > 1
      ? `已排队（第 ${position}/${queueDepth} 条），当前回合结束后处理`
      : "已排队，当前回合结束后处理",
  );
}

/** 经典+steer 真软插入 ack（``turn_steer_accepted`` · EPHEMERAL）。 */
export function notifySteerAccepted(): void {
  notifyInfo("已插入，下一工具步生效");
}

/** steer 不可注入 → 降级 queue（``degraded_from=steer``）。 */
export function notifySteerDegradedToQueue(): void {
  notifyInfo("当前无法插入，已改为排队，将在本回合结束后发送");
}
