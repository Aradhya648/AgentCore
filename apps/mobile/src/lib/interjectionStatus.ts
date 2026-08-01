/** S2 四态文案（legacy `delivered` ≡ `received`）。心智：只对主 Agent 说话。 */
export function interjectionStatusLabel(
  status: string | null | undefined,
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

export function interjectionStatusTone(
  status: string | null | undefined,
): "received" | "queued" | "failed" | "addressed" {
  if (status === "queued") return "queued";
  if (status === "failed") return "failed";
  if (status === "addressed") return "addressed";
  return "received";
}
