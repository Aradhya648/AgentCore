import { api } from "@/services/api";
import type { SidecarPermissionPreset } from "@shared/sidecar-contract";

/**
 * Map user-level AutonomyPolicy (新会话默认) → conversation PermissionPreset.
 * always_ask→observe / first_grant→workspace / full_auto→full_trust.
 */
export function autonomyToPreset(
  policy: "always_ask" | "first_grant" | "full_auto",
): SidecarPermissionPreset {
  switch (policy) {
    case "always_ask":
      return "observe";
    case "full_auto":
      return "full_trust";
    default:
      return "workspace";
  }
}

export function presetToAutonomy(
  preset: SidecarPermissionPreset,
): "always_ask" | "first_grant" | "full_auto" {
  switch (preset) {
    case "observe":
      return "always_ask";
    case "full_trust":
      return "full_auto";
    default:
      return "first_grant";
  }
}

/** Labels for the three session permission modes (Composer / StatusStrip / 开工卡). */
export const PERMISSION_PRESET_LABELS: Record<
  SidecarPermissionPreset,
  { short: string; description: string }
> = {
  observe: {
    short: "只观察",
    description: "不跑代码/终端；写文件逐次审批。",
  },
  workspace: {
    short: "开工授权",
    description: "开工卡一次授权本委派所需能力（推荐）。",
  },
  full_trust: {
    short: "完全信任",
    description: "AI 将与你同权执行命令；跳过开工卡与执行审批。",
  },
};

const PRESET_ORDER: SidecarPermissionPreset[] = [
  "observe",
  "workspace",
  "full_trust",
];

/**
 * Short label for a raw permission-preset string from audit `detail`
 * (回合档位 chip · 权限模式切换系统行). Unknown / non-preset values → null so the
 * caller can fall back to the raw value or hide the chrome.
 */
export function permissionPresetShortLabel(raw: unknown): string | null {
  if (typeof raw !== "string") return null;
  if (raw in PERMISSION_PRESET_LABELS) {
    return PERMISSION_PRESET_LABELS[raw as SidecarPermissionPreset].short;
  }
  return null;
}

/** True when ``next`` is a stricter (lower-privilege) mode than ``current``. */
export function isPermissionDowngrade(
  current: SidecarPermissionPreset,
  next: SidecarPermissionPreset,
): boolean {
  return PRESET_ORDER.indexOf(next) < PRESET_ORDER.indexOf(current);
}

/** Cache of the user's default autonomy → used only to seed *new* conversations. */
let cachedDefault: SidecarPermissionPreset | null = null;

export async function resolveDefaultPermissionPreset(): Promise<SidecarPermissionPreset> {
  if (cachedDefault) return cachedDefault;
  try {
    const d = await api.get<{
      policy: "always_ask" | "first_grant" | "full_auto";
    }>("/v1/users/me/autonomy");
    cachedDefault = autonomyToPreset(d.policy);
    return cachedDefault;
  } catch {
    return "workspace";
  }
}

export function setCachedDefaultPermissionPreset(
  policy: "always_ask" | "first_grant" | "full_auto",
): void {
  cachedDefault = autonomyToPreset(policy);
}

export function clearDefaultPermissionPresetCache(): void {
  cachedDefault = null;
}

/** Persist a mid-session permission mode switch. */
export async function setConversationPermissionPreset(
  conversationId: string,
  permissionPreset: SidecarPermissionPreset,
): Promise<SidecarPermissionPreset> {
  const res = await api.put<{ permission_preset: SidecarPermissionPreset }>(
    `/v1/conversations/${conversationId}/permission-preset`,
    { permission_preset: permissionPreset },
  );
  return res.permission_preset;
}

/**
 * Resolve the permission mode for a conversation (React Query cache first, else GET).
 * Sidecar turns send this every startTurn / resume — must match DB SSO
 * (``conversations.permission_preset``), never fall back to the user's *new-session*
 * default when the conversation already exists.
 */
export async function resolveConversationPermissionPreset(
  conversationId: string,
): Promise<SidecarPermissionPreset | undefined> {
  try {
    const { getConversations } = await import("@/hooks/useConversations");
    const conv = getConversations().find((c) => c.id === conversationId);
    if (conv?.permissionPreset) return conv.permissionPreset;
  } catch {
    // query cache may be unavailable in tests
  }
  try {
    const res = await api.get<{ permission_preset?: SidecarPermissionPreset }>(
      `/v1/conversations/${conversationId}`,
    );
    if (res.permission_preset) return res.permission_preset;
  } catch {
    // network / 404 — last resort below
  }
  return resolveDefaultPermissionPreset();
}
