/**
 * Heuristic flags on review / QC worker output (简介流水线等).
 * Phase-1 of 中间可见性: surface low scores & direction issues on graph nodes
 * without waiting for structured `contract` (P1).
 *
 * Only runs on review-like roles — scanning every worker mislabels researchers
 * who write 「从整体方向把握…」 as 「方向风险」.
 */
export type ReviewConcernLevel = "warning" | "critical";

const REVIEW_ROLE_RE = /审校|评审|审查|质检|复核|QC|review/i;

const DIRECTION_PATTERNS = [
  /方向(?:不对|偏|问题|有误)/,
  /整体方向/,
  /建议(?:叫停|重写|推翻)/,
  /致命/,
  /根本性/,
];

/** Playbook task id `review` or role names like 「学术审校员」. */
export function isReviewLikeWorker(
  role: string,
  runId?: string | null,
): boolean {
  if (runId === "review") return true;
  return REVIEW_ROLE_RE.test(role.trim());
}

/** Score tokens only in explicit grading context (avoids 「7/10 完成」 dates). */
function collectReviewScores(text: string): number[] {
  const scores: number[] = [];
  const patterns = [
    /(?:评分|得分|打分)[^。\n]{0,24}?(\d{1,2})\s*\/\s*10/g,
    /(\d{1,2})\s*\/\s*10\s*分/g,
    /综合[^。\n]{0,20}?(\d{1,2})\s*\/\s*10/g,
  ];
  for (const re of patterns) {
    re.lastIndex = 0;
    for (let m = re.exec(text); m !== null; m = re.exec(text)) {
      const score = Number.parseInt(m[1] ?? "", 10);
      if (Number.isFinite(score)) scores.push(score);
    }
  }
  // Review prose often omits 「评分」: 「语言体验 7/10」— gate dates via lookahead.
  const bare = /(\d{1,2})\s*\/\s*10(?!\s*(?:日|号|月|年|完成|天))/g;
  bare.lastIndex = 0;
  for (let m = bare.exec(text); m !== null; m = bare.exec(text)) {
    const score = Number.parseInt(m[1] ?? "", 10);
    if (Number.isFinite(score)) scores.push(score);
  }
  return scores;
}

export type ReviewConcernContext = {
  role?: string | null;
  runId?: string | null;
};

export function detectReviewConcern(
  text: string,
  ctx?: ReviewConcernContext,
): ReviewConcernLevel | null {
  if (ctx && !isReviewLikeWorker(ctx.role ?? "", ctx.runId)) return null;

  const trimmed = text.trim();
  if (trimmed.length < 12) return null;

  for (const re of DIRECTION_PATTERNS) {
    if (re.test(trimmed)) return "critical";
  }

  for (const score of collectReviewScores(trimmed)) {
    if (score <= 5) return "critical";
    if (score <= 7) return "warning";
  }

  return null;
}
