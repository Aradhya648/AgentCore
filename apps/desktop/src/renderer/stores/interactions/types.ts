import type { InteractionStatus } from "@/types/interactionExt";
import {
  INTERACTION_ID_FIELD,
  INTERACTION_SUBMIT_PATH,
  type InteractionKind,
  type InteractionSubmitPath,
  kindFromRequiredEvent,
  kindFromResolvedEvent,
} from "./registry";

// Re-export registry surface so existing `@/stores/interactions` imports keep working.
export {
  INTERACTION_ID_FIELD,
  INTERACTION_SUBMIT_PATH,
  kindFromRequiredEvent,
  kindFromResolvedEvent,
  type InteractionKind,
  type InteractionSubmitPath,
};

/** One user-facing interaction card in the unified store (方案 §3.2). */
export interface InteractionEntry {
  id: string;
  kind: InteractionKind;
  status: InteractionStatus;
  conversationId: string;
  messageId: string;
  /** Original `*_required` (or question_posted) wire payload. */
  payload: Record<string, unknown>;
  /** Settlement payload when status is resolved (kind-specific). */
  resolution?: Record<string, unknown>;
}

/**
 * 「等你」判定（侧栏灯 / 全局提醒共用语义）：这条交互是否正把执行阻塞在用户身上。
 *
 * - 热阻塞 kind（approval / delegation_authorization / escalation）pending 或
 *   submitting 时为真——live turn 挂在卡上等答复。
 * - escalation 例外：`awaiting === "ceo"` 由 CEO 仲裁，用户无需行动 → 不算。
 * - 冷 kind（ask_user / plan_review / team_preview）恒为假：暂停的权威事实是
 *   pausedTurns store 的 durable 帧（journal 重放可能留下无帧的 pending 残影，
 *   不能拿来点灯），由调用方另行订阅。
 * - question_posted（非阻塞提问）团队没停 → 不算。
 */
export function isAwaitingUserEntry(entry: InteractionEntry): boolean {
  if (entry.status !== "pending" && entry.status !== "submitting") return false;
  if (INTERACTION_SUBMIT_PATH[entry.kind] !== "hot") return false;
  if (entry.kind === "escalation" && entry.payload.awaiting === "ceo") {
    return false;
  }
  return true;
}

export function idFromRequiredPayload(
  kind: InteractionKind,
  payload: Record<string, unknown>,
): string | null {
  const field = INTERACTION_ID_FIELD[kind];
  const raw = payload[field];
  return typeof raw === "string" && raw.length > 0 ? raw : null;
}

export function idFromResolvedPayload(
  kind: InteractionKind,
  payload: Record<string, unknown>,
): string | null {
  return idFromRequiredPayload(kind, payload);
}
