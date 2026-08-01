import type { UserInterjectionStatus } from "@/stores/execution";

/** S2 四态文案（legacy `delivered` ≡ `received`）。心智：只对主 Agent 说话。 */
export function interjectionStatusLabel(
  status: UserInterjectionStatus | string | null | undefined,
): string {
  switch (status) {
    case "queued":
      return "将在下一条回复处理";
    case "failed":
      return "未能排队，请重试或再说一次";
    case "addressed":
      return "主 Agent 已回应";
    case "received":
    case "delivered":
      return "主 Agent 已收到";
    default:
      return "主 Agent 已收到";
  }
}

export type InterjectionStatusTone =
  | "received"
  | "queued"
  | "failed"
  | "addressed";

/** Visual tone — addressed 勿假绿成功；delivered 跟 received。 */
export function interjectionStatusTone(
  status: UserInterjectionStatus | string | null | undefined,
): InterjectionStatusTone {
  if (status === "queued") return "queued";
  if (status === "failed") return "failed";
  if (status === "addressed") return "addressed";
  return "received";
}

export const INTERJECTION_TONE_CLASS: Record<InterjectionStatusTone, string> = {
  failed: "border-destructive/40 bg-destructive/10 text-destructive",
  queued: "border-border bg-muted text-muted-foreground",
  addressed: "border-border/70 bg-muted/40 text-muted-foreground",
  received: "border-border bg-muted/50 text-muted-foreground",
};
