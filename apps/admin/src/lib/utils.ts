import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

/** Tailwind-aware className merge (last conflicting utility wins). */
export function cn(...inputs: ClassValue[]): string {
  return twMerge(clsx(inputs));
}

/**
 * Money in CNY (元) from the server-provided value (the backend owns the single
 * FX rate, so the client never re-prices). Tiny non-zero spend floors to
 * "<¥0.01" so a real-but-rounding-to-zero cost never reads as free.
 */
export function fmtCny(yuan: number): string {
  if (yuan > 0 && yuan < 0.01) return "<¥0.01";
  return `¥${yuan.toFixed(2)}`;
}

/** BYOK estimate caption — always ≈-prefixed; 0 →「—」. */
export const COST_ESTIMATE_HINT =
  "按社区价目/自填单价估算，非上游账单";

export function fmtEstimatedCny(yuan: number): string {
  if (yuan <= 0) return "—";
  const body = fmtCny(yuan);
  return `≈${body}`;
}

const COMPACT = new Intl.NumberFormat("zh-CN", {
  notation: "compact",
  maximumFractionDigits: 1,
});

/** Compact formatting for large counts (e.g. token totals): 2100000 → "210万". */
export function fmtCompact(n: number): string {
  return COMPACT.format(n);
}

/** Plain integer with thousands separators. */
export function fmtInt(n: number): string {
  return n.toLocaleString("zh-CN");
}

/** Milliseconds, compacted: <1s stays "840ms", ≥1s becomes "2.4s". */
export function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/** ISO date "2026-06-18" → "06-18" for compact trend-chart axes. */
export function mmdd(iso: string): string {
  const [, m, d] = iso.split("-");
  return m && d ? `${m}-${d}` : iso;
}

/** ISO timestamp → "MM-DD HH:mm" in the viewer's local zone (compact log axis). */
export function fmtTime(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const p = (n: number) => String(n).padStart(2, "0");
  return `${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`;
}

const NANO_PER_USD = 1_000_000_000;

/**
 * Convert integer nano-USD (the ledger's canonical money unit) to CNY (元) via the
 * single server-provided rate. Used for the raw-nano fields (trend / per-user
 * rows) that don't ship a pre-computed `cny_total` like the window breakdowns do.
 */
export function nanoUsdToCny(nano: number, cnyPerUsd: number): number {
  return (nano / NANO_PER_USD) * cnyPerUsd;
}

/** nano-USD → display CNY string; `estimated` adds ≈ prefix. */
export function fmtNanoCny(
  nano: number,
  cnyPerUsd: number,
  estimated = false,
): string {
  if (nano <= 0) return "—";
  const yuan = nanoUsdToCny(nano, cnyPerUsd);
  return estimated ? fmtEstimatedCny(yuan) : fmtCny(yuan);
}

/** Integer nano-USD → USD (the unit global quota thresholds are configured in). */
export function nanoUsdToUsd(nano: number): number {
  return nano / NANO_PER_USD;
}

/**
 * Ledger `cost_events.role` → 大众-facing zh label, mirroring the desktop/mobile
 * 工资单 so an operator reads「视觉读图」not raw「vision」. Unknown roles fall back
 * to the raw string. `vision` tags a board_read 读图 sub-call to a separate vision
 * model (AI协作白板.md §九.4); `title`/`memory` are off-turn background calls.
 */
const ROLE_LABELS: Record<string, string> = {
  captain: "CEO",
  member: "队员",
  arena: "辩论",
  title: "标题生成",
  memory: "记忆整理",
  vision: "视觉读图",
};

/** A ledger role's zh label; unknown roles fall back to the raw string. */
export function roleLabel(role: string): string {
  return ROLE_LABELS[role] ?? role;
}

/** Number of `--agent-N` identity tokens defined in styles/globals.css. */
const AGENT_PALETTE_SIZE = 8;

/**
 * Deterministic FNV-1a string hash, so a given role always maps to the same
 * identity slot across reloads — never `Math.random` / insertion order, which
 * would reshuffle colors. Mirrors the desktop renderer's `agentIdentity` (each
 * frontend reimplements presentation helpers, no shared business logic).
 */
function hashRole(role: string): number {
  let h = 0x811c9dc5;
  for (let i = 0; i < role.length; i++) {
    h ^= role.charCodeAt(i);
    h = Math.imul(h, 0x01000193);
  }
  return h >>> 0;
}

/**
 * The role's identity color as a CSS `var(--agent-N)` reference (color-tokens.mdc
 * 角色身份色 — use inline; these are semantic OKLCH tokens, not ad-hoc colors).
 * Blank role falls back to slot 1.
 */
export function agentColorVar(role: string): string {
  const key = role.trim();
  const idx = key ? (hashRole(key) % AGENT_PALETTE_SIZE) + 1 : 1;
  return `var(--agent-${idx})`;
}
