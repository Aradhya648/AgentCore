import type { Conversation } from "@/stores/conversation";

export type RecencyGroupId =
  | "pinned"
  | "today"
  | "yesterday"
  | "week"
  | "earlier";

export type RecencyGroup = {
  id: RecencyGroupId;
  label: string;
  items: Conversation[];
};

const GROUP_ORDER: RecencyGroupId[] = [
  "pinned",
  "today",
  "yesterday",
  "week",
  "earlier",
];

const GROUP_LABEL: Record<RecencyGroupId, string> = {
  pinned: "置顶",
  today: "今天",
  yesterday: "昨天",
  week: "本周",
  earlier: "更早",
};

function startOfLocalDay(d: Date): number {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
}

function bucketForUpdatedAt(
  iso: string,
  now: Date,
): Exclude<RecencyGroupId, "pinned"> {
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return "earlier";
  const day = startOfLocalDay(new Date(t));
  const today = startOfLocalDay(now);
  const dayMs = 86_400_000;
  if (day === today) return "today";
  if (day === today - dayMs) return "yesterday";
  // 「本周」= 今天往前 6 天内（不含今天/昨天已分出的两天）
  if (day > today - 7 * dayMs) return "week";
  return "earlier";
}

/**
 * Group a recency-sorted list into 置顶 / 今天 / 昨天 / 本周 / 更早.
 * Pinned items form their own leading group; unpinned fill time buckets.
 * Empty groups are omitted. Order within each group is preserved.
 */
export function groupConversationsByRecency(
  list: Conversation[],
  now: Date = new Date(),
): RecencyGroup[] {
  const buckets: Record<RecencyGroupId, Conversation[]> = {
    pinned: [],
    today: [],
    yesterday: [],
    week: [],
    earlier: [],
  };
  for (const c of list) {
    if (c.pinned) {
      buckets.pinned.push(c);
      continue;
    }
    buckets[bucketForUpdatedAt(c.updatedAt, now)].push(c);
  }
  return GROUP_ORDER.filter((id) => buckets[id].length > 0).map((id) => ({
    id,
    label: GROUP_LABEL[id],
    items: buckets[id],
  }));
}
