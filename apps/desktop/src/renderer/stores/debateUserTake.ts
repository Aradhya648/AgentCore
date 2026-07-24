import { create } from "zustand";

/**
 * 站队（用户对一场辩论的**倾向**）的**会话内客户端态**（前端UX设计.md §4.4 · 辩论编排设计.md §6.7）——
 * 记录用户倾向某一方（某 `side.key`），**绝不碰后端裁决**（守 AI 中立：站队只对比）。按回合 id
 * （`turnId` = 该回合的 message / execution id）分桶。
 *
 * **会话内态、不持久化**：站队仅在当前打开的会话里有效，重载 / 翻页后重置——它是「看辩论时顺手标个
 * 倾向」的轻量标记，不值得专用持久化表（拍板功能与 `debate_user_takes` 表已一并移除）。
 */
interface DebateStanceState {
  /** 各回合的站队倾向：`turnId → side.key`（缺省 / 未站队为 `null`）。 */
  byTurn: Record<string, string | null>;
  setStance: (turnId: string, stance: string | null) => void;
}

export const useDebateUserTake = create<DebateStanceState>((set) => ({
  byTurn: {},
  setStance: (turnId, stance) =>
    set((s) => ({ byTurn: { ...s.byTurn, [turnId]: stance } })),
}));

/** 读取某回合的站队倾向（缺省 `null`）。 */
export function useDebateTake(turnId: string): { stance: string | null } {
  const stance = useDebateUserTake((s) => s.byTurn[turnId] ?? null);
  return { stance };
}
