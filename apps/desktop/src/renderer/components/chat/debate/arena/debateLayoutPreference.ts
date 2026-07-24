import { uiGet, uiSet } from "@/lib/uiStorage";
import type { Stance } from "@/stores/execution";
import type { DebateModel } from "../model";

/** 辩论室剧本主列布局：并排对照 vs 上下单栏（长文阅读）。 */
export type DebateArenaLayout = "split" | "stack";

const STORAGE_KEY = "debate-arena-layout";

/** 赛事页外层容器宽度（记分牌 + 剧本主列共用）。 */
export const DEBATE_ARENA_PAGE_MAX = "max-w-7xl";

export function loadDebateArenaLayout(): DebateArenaLayout {
  return uiGet<string>(STORAGE_KEY) === "stack" ? "stack" : "split";
}

export function saveDebateArenaLayout(layout: DebateArenaLayout): void {
  uiSet(STORAGE_KEY, layout);
}

/** 仅正反 2 方、有 pro/con 语义身份时可并排。 */
export function canUseSplitLayout(model: DebateModel): boolean {
  if (model.form !== "debate") return false;

  if (model.sides?.length === 2) {
    const keys = new Set(model.sides.map((s) => s.key));
    if (keys.has("pro") && keys.has("con")) return true;
  }

  // 进行中 2 方正反：liveTwoSideRounds 会给 side 打上 pro/con stance
  return model.rounds.some((r) =>
    r.sides.some((s) => s.stance === "pro" || s.stance === "con"),
  );
}

/**
 * 单一「按阵营分左右」判据：**stance 优先、key 兜底**。辩论室三处并排渲染（立论 / 质询 / 结辩）
 * 共用此判据以消除判据漂移——后端各方的语义 key 是主持人自定、未必是字面 `pro`/`con`，唯有
 * `stance` 恒为 `pro`/`con`；若只认 key，「自定 key」的辩论会分不出正反、退化成上下堆叠。
 * `others` 收纳既非 pro 也非 con 的方（多方场景），由调用方顺次堆叠。
 */
export function partitionSides<T>(
  items: readonly T[],
  keyOf: (item: T) => string,
  stanceOf?: (item: T) => Stance | null,
): { pro: T | undefined; con: T | undefined; others: T[] } {
  const isPro = (s: T) => stanceOf?.(s) === "pro" || keyOf(s) === "pro";
  const isCon = (s: T) => stanceOf?.(s) === "con" || keyOf(s) === "con";
  const pro = items.find(isPro);
  const con = items.find((s) => s !== pro && isCon(s));
  const others = items.filter((s) => s !== pro && s !== con);
  return { pro, con, others };
}
