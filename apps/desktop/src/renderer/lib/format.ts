/** 把字节数格式化为人类可读字符串。 */
export function formatBytes(bytes: number): string {
  if (bytes < 1024) return `${bytes} B`;
  const units = ["KB", "MB", "GB", "TB"];
  let value = bytes / 1024;
  let i = 0;
  while (value >= 1024 && i < units.length - 1) {
    value /= 1024;
    i++;
  }
  return `${value.toFixed(value < 10 ? 1 : 0)} ${units[i]}`;
}

const CJK_RANGE = /[\u3040-\u30ff\u3400-\u9fff\uac00-\ud7af\uff00-\uffef]/;

/**
 * 粗估文本的 token 数，用于流式进度展示（非计费用途）。
 *
 * 真实 token 数只有 LLM 网关在回合结束时给出（usage）；流式过程中每个
 * delta 不带 token，因此这里用「CJK 约 1 token/字，其余约 4 字/token」的
 * 经验启发式给出一个量级感知，足够驱动节点上的实时进度。
 */
export function estimateTokens(text: string): number {
  if (!text) return 0;
  let cjk = 0;
  let other = 0;
  for (const ch of text) {
    if (CJK_RANGE.test(ch)) cjk++;
    else other++;
  }
  return Math.ceil(cjk + other / 4);
}

/** 紧凑数字：1234 → "1.2k"、2_000_000 → "2.0M"（用于 token 等大数展示）。 */
export function formatCompact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** 取文本末尾若干字符并折行成单段预览（用于 worker 节点的实时输出片段：运行中
 * 最新内容在末尾，tail 才是「正在写什么」）。 */
export function tailText(text: string, max = 80): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  return `…${flat.slice(flat.length - max)}`;
}

/** 取文本开头若干字符并折行成单段预览（用于 CEO 汇总节点：成稿答案的开头通常即
 * 结论/主旨，比取末尾片段更能代表内容，避免长答案截出半句结尾乱码）。 */
export function headText(text: string, max = 80): string {
  const flat = text.replace(/\s+/g, " ").trim();
  if (flat.length <= max) return flat;
  return `${flat.slice(0, max)}…`;
}

function sameCalendarDay(a: Date, b: Date): boolean {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  );
}

/** 相对时间：「刚刚」/「N 分钟前」/「N 小时前」/「N 天前」。非法输入返回空串。 */
export function timeAgo(date: string | Date): string {
  const t = new Date(date).getTime();
  if (Number.isNaN(t)) return "";
  const ms = Date.now() - t;
  const min = Math.floor(ms / 60_000);
  if (min < 1) return "刚刚";
  if (min < 60) return `${min} 分钟前`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr} 小时前`;
  const d = Math.floor(hr / 24);
  return `${d} 天前`;
}

/** 消息时刻 "HH:MM"（线程内日期由分隔条承担）。非法输入返回空串。 */
export function formatMessageTimeOfDay(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const pad = (n: number) => String(n).padStart(2, "0");
  return `${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/**
 * IM 线程日期分隔条：今天 / 昨天 / M月D日 / YYYY年M月D日。非法输入返回空串。
 */
export function formatDateDivider(iso: string): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return "";
  const now = new Date();
  if (sameCalendarDay(d, now)) return "今天";
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameCalendarDay(d, yesterday)) return "昨天";
  const md = `${d.getMonth() + 1}月${d.getDate()}日`;
  if (d.getFullYear() === now.getFullYear()) return md;
  return `${d.getFullYear()}年${md}`;
}

/**
 * 消息时间戳展示串（侧栏预览等无日期上下文处）：今天显 "HH:MM"，昨天 "昨天 HH:MM"，
 * 同年 "M月D日 HH:MM"，跨年 "YYYY年M月D日 HH:MM"。非法输入返回空串。
 */
export function formatMessageTime(iso: string): string {
  const tod = formatMessageTimeOfDay(iso);
  if (!tod) return "";
  const d = new Date(iso);
  const now = new Date();
  if (sameCalendarDay(d, now)) return tod;
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (sameCalendarDay(d, yesterday)) return `昨天 ${tod}`;
  const md = `${d.getMonth() + 1}月${d.getDate()}日`;
  if (d.getFullYear() === now.getFullYear()) return `${md} ${tod}`;
  return `${d.getFullYear()}年${md} ${tod}`;
}

/** 毫秒时长 → 人类可读："45s" / "2m34s" / "1h2m"（用于任务用时摘要）。 */
export function formatDuration(ms: number): string {
  const totalSec = Math.round(ms / 1000);
  if (totalSec < 60) return `${totalSec}s`;
  const h = Math.floor(totalSec / 3600);
  const m = Math.floor((totalSec % 3600) / 60);
  const s = totalSec % 60;
  if (h > 0) return `${h}h${m}m`;
  return `${m}m${s}s`;
}

/** 1 USD = 10^9 nano-USD：台账/接口里钱的规范单位（整数，绝不用 float）。 */
const NANO_PER_USD = 1_000_000_000;

/**
 * BYOK 估算金额的轻量说明（tooltip / title）——与平台记账 ¥ 视觉分离，
 * 明确「非上游账单」。
 */
export const COST_ESTIMATE_HINT = "按社区价目/自填单价估算，非上游账单";

/** 费用位标注：自带密钥场景（credential_source=user / estimated_total）。 */
export const COST_ESTIMATE_LABEL = "自带密钥·估算";

/**
 * 费用位标注：BYOK 且三层价卡全落空（`pricing_source=unpriced`）。
 * 有真实花费但平台无价可算——显式标注，不得以「省略费用段」暗示免费
 * （拍板 2026-07-20：未计价运行显式标识，金额位仍显「—」绝不冒充数字）。
 */
export const COST_UNPRICED_LABEL = "自带密钥·未计价";

/** 未计价标注的轻量说明（tooltip / title）。 */
export const COST_UNPRICED_HINT =
  "平台无此模型价目（未填单价、社区价目缺），实际费用以上游供应商账单为准";

/**
 * 把整数 nano-USD 成本折算成人民币展示串（大众面，§7.2）。
 *
 * 钱一律以整数 nano-USD 流转（1 USD = 1e9），绝不用 float；汇率 `cnyPerUsd` 由
 * 后端单一来源下发（`/usage/summary`），前端不写死。约定（§7.5）：0 / 无花销显
 * 「—」（不显「¥0.00」）；有花销但折算不足 1 分显「<¥0.01」。
 */
export function formatCost(nanoUsd: number, cnyPerUsd: number): string {
  if (nanoUsd <= 0) return "—";
  const yuan = (nanoUsd / NANO_PER_USD) * cnyPerUsd;
  if (yuan < 0.01) return "<¥0.01";
  return `¥${yuan.toFixed(2)}`;
}

/**
 * 把整数 nano-USD 成本格式化为 USD 展示串（power 面，§7.2）：`$0.0123`。
 *
 * 同 {@link formatCost}：0 / 无花销显「—」；有花销但不足 $0.0001 显「<$0.0001」。
 */
export function formatUsd(nanoUsd: number): string {
  if (nanoUsd <= 0) return "—";
  const usd = nanoUsd / NANO_PER_USD;
  if (usd < 0.0001) return "<$0.0001";
  return `$${usd.toFixed(4)}`;
}

/**
 * 展示金额：平台记账走 {@link formatCost}；估算金额一律带「≈」前缀，
 * 不得与记账 ¥ 混淆。0 / 无值仍显「—」（`pricing_source=unpriced` 同此）。
 */
export function formatDisplayCost(
  nanoUsd: number,
  cnyPerUsd: number,
  estimated = false,
): string {
  const base = formatCost(nanoUsd, cnyPerUsd);
  if (base === "—" || !estimated) return base;
  return `≈${base}`;
}

/** 同 {@link formatDisplayCost} 的 USD 面。 */
export function formatDisplayUsd(nanoUsd: number, estimated = false): string {
  const base = formatUsd(nanoUsd);
  if (base === "—" || !estimated) return base;
  return `≈${base}`;
}

/** SSE / fold `CostBreakdown` 叶子上挑「记账 total vs 估算 estimated_total」。 */
export function pickCostMoney(
  cost:
    | {
        total: number;
        estimated_total?: number | null;
        /** Live BYOK often keeps money in `total` with estimated/user_defined source. */
        pricing_source?: string | null;
      }
    | null
    | undefined,
): { nano: number; estimated: boolean } | null {
  if (!cost) return null;
  if (cost.total > 0) {
    // user_defined = BYOK 自填单价；live SSE 金额仍在 total 上。
    const byok = cost.pricing_source === "user_defined";
    return { nano: cost.total, estimated: byok };
  }
  const est = cost.estimated_total;
  if (est != null && est > 0) return { nano: est, estimated: true };
  return { nano: 0, estimated: false };
}

/** 费用展示串：有金额时附带「自带密钥·估算」标注。 */
export function formatCostCaption(
  nanoUsd: number,
  cnyPerUsd: number,
  estimated = false,
): string {
  const base = formatDisplayCost(nanoUsd, cnyPerUsd, estimated);
  if (base === "—" || !estimated) return base;
  return `${base} ${COST_ESTIMATE_LABEL}`;
}
