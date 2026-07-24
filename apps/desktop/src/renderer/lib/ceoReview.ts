import type { CeoReviewSummary } from "@/types/events";

/**
 * 宽松 dict（wire / journal 重放 / recovery 快照）→ 规范 {@link CeoReviewSummary}。
 * absent / 非对象 / 三字段全空 → undefined（可选字段正常兼容，界面不留空壳）。
 * ``source`` 可选（旧帧缺省）；仅识别 ``"llm"`` / ``"deterministic"``。
 */
export function toCeoReview(raw: unknown): CeoReviewSummary | undefined {
  if (typeof raw !== "object" || raw === null) return undefined;
  const obj = raw as Record<string, unknown>;
  const strs = (v: unknown): string[] =>
    Array.isArray(v)
      ? v.filter(
          (x): x is string => typeof x === "string" && x.trim().length > 0,
        )
      : [];
  const conclusion =
    typeof obj.conclusion === "string" ? obj.conclusion.trim() : "";
  const risks = strs(obj.risks);
  const suggestions = strs(obj.suggestions);
  if (!conclusion && risks.length === 0 && suggestions.length === 0) {
    return undefined;
  }
  const sourceRaw = obj.source;
  const source =
    sourceRaw === "llm" || sourceRaw === "deterministic"
      ? sourceRaw
      : undefined;
  return {
    conclusion,
    risks,
    suggestions,
    ...(source ? { source } : {}),
  };
}
