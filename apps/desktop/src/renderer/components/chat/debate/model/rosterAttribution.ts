/**
 * Phase 3 真·多模型署名：「正方 X · 反方 Y · 裁判 Z」。
 * 无 model 字段（同模型场）→ null，零 UI 噪声。
 */
import { modelVendorLabel } from "./labels";

export type RosterModelSlot = {
  name: string;
  model?: string | null;
  origin?: "platform" | "byok" | null;
};

export type ModeratorModelSlot = {
  model?: string | null;
  origin?: "platform" | "byok" | null;
};

/** 单槽展示名：厂商友好名；BYOK 时附 ·BYOK（必要时 origin）。 */
export function formatModelSlotLabel(
  model: string | null | undefined,
  origin?: "platform" | "byok" | null,
): string | null {
  const label = modelVendorLabel(model);
  if (!label) return null;
  if (origin === "byok") return `${label}·BYOK`;
  return label;
}

/**
 * 有任一方 / 裁判带 model 才出署名行；全缺 → null（同模型场保持旧观感）。
 */
export function formatCrossModelRosterLine(
  sides: readonly RosterModelSlot[],
  moderator?: ModeratorModelSlot | null,
): string | null {
  const hasAny =
    sides.some((s) => Boolean((s.model ?? "").trim())) ||
    Boolean((moderator?.model ?? "").trim());
  if (!hasAny) return null;

  const parts: string[] = [];
  for (const s of sides) {
    const slot = formatModelSlotLabel(s.model, s.origin);
    if (slot) parts.push(`${s.name} ${slot}`);
  }
  const mod = formatModelSlotLabel(moderator?.model, moderator?.origin);
  if (mod) parts.push(`裁判 ${mod}`);
  return parts.length > 0 ? parts.join(" · ") : null;
}
