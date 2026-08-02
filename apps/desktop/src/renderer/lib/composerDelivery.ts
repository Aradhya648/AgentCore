import { assistantProjectionId, getRuntime } from "@/stores/conversation";
import { useExecutionStore } from "@/stores/execution";

export type MessageDelivery = "steer" | "queue";

/**
 * 协调活跃 ≈ 当前回合已有团队 plan（run_plan）。
 * P1 后默认 delivery 不再依赖此判定（经典也可 soft-insert）；
 * 仍导出供协调路径 / UI 区分插话投影用。
 */
export function isCoordinationActive(
  conversationId: string | null | undefined,
): boolean {
  if (!conversationId) return false;
  const msgs = getRuntime(conversationId).messages;
  for (let i = msgs.length - 1; i >= 0; i--) {
    const m = msgs[i];
    if (m.role !== "assistant") continue;
    const key = assistantProjectionId(m);
    const exec = useExecutionStore.getState().byId[key];
    if (exec?.plan) return true;
    return false;
  }
  return false;
}

/**
 * 默认 delivery（P1）：
 * - 空闲 → steer
 * - 生成中（经典 / 协调）→ steer（「插入」）
 * 强制 queue 仅 Ctrl/Cmd+Enter / 显式 opts.delivery。
 * 不可注入时由服务端降级 ``turn_queued`` + ``degraded_from=steer``。
 */
export function resolveDefaultDelivery(
  _isGenerating: boolean,
  _conversationId: string | null | undefined,
): MessageDelivery {
  return "steer";
}
