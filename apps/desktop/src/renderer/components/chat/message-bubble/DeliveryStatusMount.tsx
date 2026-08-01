import type { DeliveryStatusPayload } from "@/types/events";

/**
 * 交付验收大卡已撤（用户面第①步）：delivered / notes 静默；
 * partial / blocked 仅一句轻提示（无按钮、无缺口明细）。产物清单仍走 FileArtifactsCard。
 */
export function DeliveryStatusMount({
  status,
}: {
  status: DeliveryStatusPayload | null;
}) {
  if (!status) return null;
  if (status.state !== "partial" && status.state !== "blocked") return null;
  const text =
    status.summary.trim() ||
    (status.state === "blocked" ? "交付未满足" : "部分交付未满足");
  return (
    <p
      className="mt-2 text-sm text-muted-foreground"
      data-testid="delivery-shortfall-hint"
    >
      {text}
    </p>
  );
}
