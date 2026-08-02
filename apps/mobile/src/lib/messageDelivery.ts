/**
 * 同对话再发 · delivery（运行时三模型 · Steer/Queue）。
 * 默认一律 steer（含 busy）；强制 queue 仅由 UI 显式入口传入。
 * 经典无 accepting 窗口时服务端回落 queue（`degraded_from=steer`）。
 */
import type { ProjectedTurn } from "@agentcore/protocol-conformance";

export type MessageDelivery = "steer" | "queue";

/**
 * 当前 live 投影是否像「协调可插」（团队 / 辩论 / 已有插话）。
 * 仅作文案/按钮标签启发式；不再驱动默认 delivery。
 */
export function isLiveInterruptible(
  projection: ProjectedTurn | null | undefined,
): boolean {
  if (!projection) return false;
  if (projection.runs.length > 0) return true;
  if (projection.debate != null) return true;
  if (projection.debateRounds.length > 0) return true;
  if (projection.userInterjections.length > 0) return true;
  return false;
}

/** 默认 delivery：空闲 / busy 均 steer；强制 queue 由 UI 显式传入。 */
export function defaultDelivery(_opts?: {
  busy?: boolean;
  /** @deprecated 不再影响默认；仅保留调用方兼容 */
  interruptible?: boolean;
}): MessageDelivery {
  return "steer";
}
