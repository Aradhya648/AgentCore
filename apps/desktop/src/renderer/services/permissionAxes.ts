import { api } from "@/services/api";
import type {
  SidecarCommandAxis,
  SidecarFileWriteAxis,
  SidecarHostAxis,
  SidecarPermissionAxes,
  SidecarTeamKickoffAxis,
} from "@shared/sidecar-contract";

/** User-global default recipe id (seeds new conversations). */
export type AutonomyRecipe = "cautious" | "less_interrupt" | "managed";

export type PermissionAxes = SidecarPermissionAxes;

export const DEFAULT_PERMISSION_AXES: PermissionAxes = {
  file_write: "session",
  command: "auto",
  team_kickoff: "rules",
  host: "ask",
};

/** Built-in recipes → exact axis tuples (含 host). */
export const RECIPE_AXES: Record<AutonomyRecipe, PermissionAxes> = {
  cautious: {
    file_write: "ask",
    command: "ask",
    team_kickoff: "rules",
    host: "off",
  },
  less_interrupt: DEFAULT_PERMISSION_AXES,
  managed: {
    file_write: "session",
    command: "auto",
    team_kickoff: "skip",
    host: "session",
  },
};

export const RECIPE_ORDER: AutonomyRecipe[] = [
  "cautious",
  "less_interrupt",
  "managed",
];

export const RECIPE_LABELS: Record<
  AutonomyRecipe,
  { short: string; description: string }
> = {
  cautious: {
    short: "谨慎",
    description: "改文件每次问 · 执行每次确认 · 组队按规则 · 本机关闭",
  },
  less_interrupt: {
    short: "少打断",
    description: "改文件本会话信任 · 自动执行 · 组队按规则 · 本机每次确认",
  },
  managed: {
    short: "托管",
    description: "改文件本会话信任 · 自动执行 · 不弹组队卡 · 本机会话信任",
  },
};

export const FILE_WRITE_OPTIONS: {
  value: SidecarFileWriteAxis;
  short: string;
  description: string;
}[] = [
  {
    value: "ask",
    short: "每次确认",
    description: "每次改文件都要你确认。",
  },
  {
    value: "session",
    short: "本会话信任",
    description: "本会话内可逆写入免逐次确认。",
  },
];

export const COMMAND_OPTIONS: {
  value: SidecarCommandAxis;
  short: string;
  description: string;
}[] = [
  {
    value: "ask",
    short: "每次确认",
    description: "不挂开工执行授权；执行类仍逐次审。",
  },
  {
    value: "kickoff",
    short: "开工时确认",
    description: "在开工卡上确认后，本回合可跑代码/终端。",
  },
  {
    value: "auto",
    short: "自动执行",
    description:
      "执行类（代码/终端/浏览器等）与桌面提醒免审；Host/MCP 仍按本机轴。",
  },
];

export const TEAM_KICKOFF_OPTIONS: {
  value: SidecarTeamKickoffAxis;
  short: string;
  description: string;
}[] = [
  {
    value: "always",
    short: "总是确认",
    description: "组队前总是先给你看组团卡。",
  },
  {
    value: "rules",
    short: "重要时确认",
    description: "按现行规则决定是否弹出组团卡。",
  },
  {
    value: "skip",
    short: "不弹组队卡",
    description: "组队不弹组团卡。",
  },
];

export const HOST_OPTIONS: {
  value: SidecarHostAxis;
  short: string;
  description: string;
}[] = [
  {
    value: "off",
    short: "关闭",
    description: "本机 Host 面整面关闭（不影响工作区终端）。",
  },
  {
    value: "ask",
    short: "每次确认",
    description: "本机 Host 敏感操作逐次确认。",
  },
  {
    value: "session",
    short: "本会话信任",
    description: "本会话信任本机 Host（熔断除外）。",
  },
];

/** Compact tokens for custom-axes badge (file · command · team · host). */
const FILE_WRITE_BADGE: Record<SidecarFileWriteAxis, string> = {
  ask: "逐次",
  session: "信任",
};
const COMMAND_BADGE: Record<SidecarCommandAxis, string> = {
  ask: "每次",
  kickoff: "开工",
  auto: "免审",
};
const TEAM_KICKOFF_BADGE: Record<SidecarTeamKickoffAxis, string> = {
  always: "总挂",
  rules: "规则",
  skip: "跳卡",
};
const HOST_BADGE: Record<SidecarHostAxis, string> = {
  off: "本机关",
  ask: "本机问",
  session: "本机信",
};

/** Four-axis short summary when not matching a built-in recipe. */
export function axesCustomSummary(axes: PermissionAxes): string {
  return [
    FILE_WRITE_BADGE[axes.file_write],
    COMMAND_BADGE[axes.command],
    TEAM_KICKOFF_BADGE[axes.team_kickoff],
    HOST_BADGE[axes.host],
  ].join(" · ");
}
export function axesEqual(a: PermissionAxes, b: PermissionAxes): boolean {
  return (
    a.file_write === b.file_write &&
    a.command === b.command &&
    a.team_kickoff === b.team_kickoff &&
    a.host === b.host
  );
}

/** Illegal: command=auto ∧ file_write=ask. */
export function isIllegalAxes(axes: PermissionAxes): boolean {
  return axes.command === "auto" && axes.file_write === "ask";
}

export function normalizeAxes(
  raw: Partial<PermissionAxes> | null | undefined,
): PermissionAxes {
  const next: PermissionAxes = {
    file_write: raw?.file_write ?? DEFAULT_PERMISSION_AXES.file_write,
    command: raw?.command ?? DEFAULT_PERMISSION_AXES.command,
    team_kickoff: raw?.team_kickoff ?? DEFAULT_PERMISSION_AXES.team_kickoff,
    host: raw?.host ?? DEFAULT_PERMISSION_AXES.host,
  };
  if (isIllegalAxes(next)) return DEFAULT_PERMISSION_AXES;
  return next;
}

export function recipeToAxes(recipe: AutonomyRecipe): PermissionAxes {
  return { ...RECIPE_AXES[recipe] };
}

/** Match axes to a built-in recipe, else ``custom``. */
export function matchRecipe(axes: PermissionAxes): AutonomyRecipe | "custom" {
  for (const id of RECIPE_ORDER) {
    if (axesEqual(axes, RECIPE_AXES[id])) return id;
  }
  return "custom";
}

export function recipeShortLabel(recipe: AutonomyRecipe | "custom"): string {
  return recipe === "custom" ? "自定义" : RECIPE_LABELS[recipe].short;
}

/** Badge / chip short name for current axes (custom → four-axis summary). */
export function axesShortLabel(axes: PermissionAxes): string {
  const recipe = matchRecipe(axes);
  return recipe === "custom"
    ? axesCustomSummary(axes)
    : RECIPE_LABELS[recipe].short;
}

/**
 * Human label for audit `previous` / `permission_axes` payloads
 * (object → recipe short name; JSON-string axes → parse then label;
 * recipe/legacy short id → label; else null — never echo raw JSON).
 */
export function permissionAxesShortLabel(raw: unknown): string | null {
  if (raw == null) return null;
  if (typeof raw === "string") {
    const trimmed = raw.trim();
    if (trimmed in RECIPE_LABELS) {
      return RECIPE_LABELS[trimmed as AutonomyRecipe].short;
    }
    // Legacy three-tier ids (old audit rows).
    const legacy: Record<string, string> = {
      observe: "谨慎",
      workspace: "少打断",
      full_trust: "托管",
      always_ask: "谨慎",
      first_grant: "少打断",
      full_auto: "托管",
    };
    if (trimmed in legacy) return legacy[trimmed];
    // Turn snapshot may store axes as json.dumps(...) string.
    if (trimmed.startsWith("{")) {
      try {
        const parsed: unknown = JSON.parse(trimmed);
        if (parsed && typeof parsed === "object" && !Array.isArray(parsed)) {
          return axesShortLabel(
            normalizeAxes(parsed as Partial<PermissionAxes>),
          );
        }
      } catch {
        return null;
      }
    }
    return null;
  }
  if (typeof raw === "object" && !Array.isArray(raw)) {
    const axes = normalizeAxes(raw as Partial<PermissionAxes>);
    return axesShortLabel(axes);
  }
  return null;
}

/** True when switching to ``command=auto`` (同权执行警示). */
export function needsAutoCommandConfirm(
  current: PermissionAxes,
  next: PermissionAxes,
): boolean {
  return next.command === "auto" && current.command !== "auto";
}

const AUTO_CONFIRM =
  "切换到「免审执行」后，执行类（代码/终端/浏览器等）与桌面提醒将免审；Host/MCP 仍按本机轴。确定继续？";

export function confirmAutoCommandIfNeeded(
  current: PermissionAxes,
  next: PermissionAxes,
): boolean {
  if (!needsAutoCommandConfirm(current, next)) return true;
  return window.confirm(AUTO_CONFIRM);
}

/** Cache of the user's default recipe → used only to seed *new* conversations. */
let cachedDefaultAxes: PermissionAxes | null = null;
/** Composer draft before a conversation exists (badge edits on empty chat). */
let composerDraftAxes: PermissionAxes | null = null;

export function setComposerDraftAxes(axes: PermissionAxes | null): void {
  composerDraftAxes = axes ? normalizeAxes(axes) : null;
}

export function peekComposerDraftAxes(): PermissionAxes | null {
  return composerDraftAxes;
}

export async function resolveDefaultPermissionAxes(): Promise<PermissionAxes> {
  if (composerDraftAxes) return composerDraftAxes;
  if (cachedDefaultAxes) return cachedDefaultAxes;
  try {
    const d = await api.get<{ policy: AutonomyRecipe }>(
      "/v1/users/me/autonomy",
    );
    cachedDefaultAxes = recipeToAxes(d.policy);
    return cachedDefaultAxes;
  } catch {
    return { ...DEFAULT_PERMISSION_AXES };
  }
}

export function setCachedDefaultRecipe(policy: AutonomyRecipe): void {
  cachedDefaultAxes = recipeToAxes(policy);
}

/** Persist user-level default recipe (seeds new conversations only). */
export async function setUserDefaultRecipe(
  policy: AutonomyRecipe,
): Promise<AutonomyRecipe> {
  const d = await api.put<{ policy: AutonomyRecipe }>("/v1/users/me/autonomy", {
    policy,
  });
  setCachedDefaultRecipe(d.policy);
  return d.policy;
}

export function clearDefaultPermissionAxesCache(): void {
  cachedDefaultAxes = null;
  composerDraftAxes = null;
}

/** Persist a mid-session axes switch. Returns the saved axes from the summary. */
export async function setConversationPermissionAxes(
  conversationId: string,
  permissionAxes: PermissionAxes,
): Promise<PermissionAxes> {
  if (isIllegalAxes(permissionAxes)) {
    throw new Error("非法权限组合：免审执行须同时「本会话信任」改文件");
  }
  const res = await api.put<{
    permission_axes?: PermissionAxes;
  }>(`/v1/conversations/${conversationId}/permission-axes`, {
    permission_axes: permissionAxes,
  });
  return normalizeAxes(res.permission_axes ?? permissionAxes);
}

/**
 * Resolve axes for a conversation (React Query cache first, else GET).
 * Sidecar turns send this every startTurn / resume — must match DB SSO.
 */
export async function resolveConversationPermissionAxes(
  conversationId: string,
): Promise<PermissionAxes | undefined> {
  try {
    const { getConversations } = await import("@/hooks/useConversations");
    const conv = getConversations().find((c) => c.id === conversationId);
    if (conv?.permissionAxes) return normalizeAxes(conv.permissionAxes);
  } catch {
    // query cache may be unavailable in tests
  }
  try {
    const res = await api.get<{ permission_axes?: PermissionAxes }>(
      `/v1/conversations/${conversationId}`,
    );
    if (res.permission_axes) return normalizeAxes(res.permission_axes);
  } catch {
    // network / 404 — last resort below
  }
  return resolveDefaultPermissionAxes();
}
