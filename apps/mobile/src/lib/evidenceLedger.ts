/**
 * 场级证据台账（evidence_ledger）前端工具——解析成稿 `#eN`、合并 live delta、徽章文案。
 * 手机自写一份（零共享业务逻辑）；语义对齐桌面 lib/evidenceLedger.ts 与提案 O1·O4·O5·O7。
 */

import type { EvidenceLedgerEntry } from "@agentcore/contract-types";

const LEDGER_ID_RE = /#e\d+/;

/** 从标记 note 抽出第一个 `#eN`；无则 null（旧自由文本出处）。 */
export function extractLedgerId(note: string): string | null {
  const m = LEDGER_ID_RE.exec(note);
  return m ? m[0] : null;
}

/** 按 id 合并增量（后写覆盖）；保持登记序。 */
export function mergeEvidenceLedger(
  existing: readonly EvidenceLedgerEntry[],
  delta: readonly EvidenceLedgerEntry[],
): EvidenceLedgerEntry[] {
  if (delta.length === 0) return [...existing];
  const order: string[] = [];
  const byId = new Map<string, EvidenceLedgerEntry>();
  for (const e of existing) {
    if (!byId.has(e.id)) order.push(e.id);
    byId.set(e.id, e);
  }
  for (const e of delta) {
    if (!byId.has(e.id)) order.push(e.id);
    byId.set(e.id, e);
  }
  return order
    .map((id) => byId.get(id))
    .filter((e): e is EvidenceLedgerEntry => e !== undefined);
}

/** id → 条目。 */
export function buildLedgerMap(
  entries: readonly EvidenceLedgerEntry[],
): ReadonlyMap<string, EvidenceLedgerEntry> {
  const m = new Map<string, EvidenceLedgerEntry>();
  for (const e of entries) m.set(e.id, e);
  return m;
}

/** 徽章可见出处：优先 site，其次 title，最后回退 id。 */
export function ledgerBadgeLabel(entry: EvidenceLedgerEntry): string {
  const site = (entry.site ?? "").trim();
  if (site) return site;
  const title = (entry.title ?? "").trim();
  if (title) return title;
  return entry.id;
}

/** tier 人话（面板：官方来源 / 权威媒体 / 自媒体 / 来源待评）。 */
export function ledgerTierLabel(tier: string | undefined): string {
  switch (tier) {
    case "official":
      return "官方来源";
    case "media":
      return "权威媒体";
    case "weak":
      return "自媒体";
    default:
      return "来源待评";
  }
}

/** tier 短标（徽章小标：官方 / 媒体 / 自媒体 / 待评）。 */
export function ledgerTierShortLabel(tier: string | undefined): string {
  switch (tier) {
    case "official":
      return "官方";
    case "media":
      return "媒体";
    case "weak":
      return "自媒体";
    default:
      return "待评";
  }
}
