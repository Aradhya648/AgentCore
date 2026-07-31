/**
 * Shared decision-card meta for ask_user + team_preview presentation.
 *
 * One table per family variant (intent / primitive) — replaces the former parallel
 * INTENT_CONFIG (CheckpointCard) and RESOLVED_META_* (TeamPreviewCard). Kind / wire
 * contracts stay untouched; this is display copy + icons only.
 */
import type { resolvedCheckpointTone } from "@/components/ui/tone-presets";
import type { KickoffPrimitive } from "@/stores/conversation";
import type { CheckpointDecision, CheckpointIntent } from "@/types/events";
import {
  Ban,
  BookOpenCheck,
  Check,
  CircleHelp,
  Clock,
  FolderTree,
  Layers,
  type LucideIcon,
  OctagonX,
  Pencil,
  Scale,
  ShieldAlert,
} from "lucide-react";

export type ResolvedToneKey = keyof typeof resolvedCheckpointTone;

export type AskIntentMeta = {
  icon: LucideIcon;
  activeCaption: string;
  cta: string;
  ctaIcon: LucideIcon;
  showFooterHint: boolean;
  resolved: Record<
    CheckpointDecision,
    { label: string; tone: ResolvedToneKey }
  >;
};

/** Decision → icon for ask_user settled stubs (tone comes from intent.resolved). */
export const ASK_RESOLVED_DECISION_ICON = {
  continue: Check,
  per_call: Check,
  adjust: Pencil,
  stop: OctagonX,
  research_first: OctagonX,
  timeout: Clock,
  orphaned: Ban,
} as const satisfies Record<CheckpointDecision, LucideIcon>;

/** Shared ask clarification copy — wire `kickoff` reuses the same shell as `decision`. */
const ASK_CLARIFY_META = {
  icon: CircleHelp,
  activeCaption: "需要你拍板",
  cta: "提交",
  ctaIcon: Check,
  showFooterHint: false,
  resolved: {
    continue: { label: "已按你的决定继续", tone: "success" },
    per_call: { label: "已按你的决定继续", tone: "success" },
    adjust: { label: "已按你的调整继续", tone: "success" },
    stop: { label: "已停止本回合", tone: "destructive" },
    research_first: { label: "已停止本回合", tone: "destructive" },
    timeout: { label: "未及时回应，已自行收尾", tone: "muted" },
    orphaned: {
      label: "已失效（回合已结束或服务已重启）",
      tone: "muted",
    },
  },
} as const satisfies AskIntentMeta;

export const ASK_INTENT_META = {
  /** Wire may still emit kickoff; UX = generic clarification (same as decision). */
  kickoff: ASK_CLARIFY_META,
  decision: ASK_CLARIFY_META,
  proposal_pick: {
    icon: Layers,
    activeCaption: "方案挑选 · 选一条推进",
    cta: "采用此方案",
    ctaIcon: Layers,
    showFooterHint: false,
    resolved: {
      continue: { label: "已选定方案", tone: "success" },
      per_call: { label: "已选定方案", tone: "success" },
      adjust: { label: "已按你的调整继续", tone: "success" },
      stop: { label: "已停止本回合", tone: "destructive" },
      research_first: { label: "已停止本回合", tone: "destructive" },
      timeout: { label: "未及时回应，已自行收尾", tone: "muted" },
      orphaned: {
        label: "已失效（回合已结束或服务已重启）",
        tone: "muted",
      },
    },
  },
  risk_ack: {
    icon: ShieldAlert,
    activeCaption: "风险确认 · 勾选本轮处理项",
    cta: "确认并继续",
    ctaIcon: ShieldAlert,
    showFooterHint: false,
    resolved: {
      continue: { label: "已确认风险处理项", tone: "success" },
      per_call: { label: "已确认风险处理项", tone: "success" },
      adjust: { label: "已按你的调整继续", tone: "success" },
      stop: { label: "已停止本回合", tone: "destructive" },
      research_first: { label: "已停止本回合", tone: "destructive" },
      timeout: { label: "未及时回应，已自行收尾", tone: "muted" },
      orphaned: {
        label: "已失效（回合已结束或服务已重启）",
        tone: "muted",
      },
    },
  },
  organize_plan: {
    icon: FolderTree,
    activeCaption: "整理方案 · 确认要执行的项",
    cta: "确认并整理",
    ctaIcon: FolderTree,
    showFooterHint: false,
    resolved: {
      continue: { label: "已确认整理方案", tone: "success" },
      per_call: { label: "已确认整理方案", tone: "success" },
      adjust: { label: "已按你的调整继续", tone: "success" },
      stop: { label: "已停止本回合", tone: "destructive" },
      research_first: { label: "已停止本回合", tone: "destructive" },
      timeout: { label: "未及时回应，已自行收尾", tone: "muted" },
      orphaned: {
        label: "已失效（回合已结束或服务已重启）",
        tone: "muted",
      },
    },
  },
  daily_review: {
    icon: BookOpenCheck,
    activeCaption: "复盘提案 · 确认要落盘的项",
    cta: "确认落盘",
    ctaIcon: BookOpenCheck,
    showFooterHint: false,
    resolved: {
      continue: { label: "已确认复盘提案", tone: "success" },
      per_call: { label: "已确认复盘提案", tone: "success" },
      adjust: { label: "已按你的调整继续", tone: "success" },
      stop: { label: "已停止本回合", tone: "destructive" },
      research_first: { label: "已停止本回合", tone: "destructive" },
      timeout: { label: "未及时回应，已自行收尾", tone: "muted" },
      orphaned: {
        label: "已失效（回合已结束或服务已重启）",
        tone: "muted",
      },
    },
  },
} as const satisfies Record<CheckpointIntent, AskIntentMeta>;

export type AskResolvedOutcome = {
  label: string;
  tone: ResolvedToneKey;
  icon: LucideIcon;
};

export function askResolvedOutcome(
  intent: CheckpointIntent,
  decision: CheckpointDecision,
): AskResolvedOutcome {
  const resolved = ASK_INTENT_META[intent].resolved[decision];
  return {
    label: resolved.label,
    tone: resolved.tone,
    icon: ASK_RESOLVED_DECISION_ICON[decision],
  };
}

type TeamResolvedRow = { label: string; icon: LucideIcon };

export type TeamPrimitiveMeta = {
  /** Inline pending marker + resume header prefix (「等你确认 · 确认后才会…」). */
  activeCaption: string;
  resumeLead: string;
  resumeCta: string;
  notePlaceholder: string;
  resolved: Record<Exclude<CheckpointDecision, "per_call">, TeamResolvedRow>;
  /** continue + non-empty note overrides the continue label. */
  continueWithNote: TeamResolvedRow;
};

export const TEAM_PRIMITIVE_META = {
  delegate: {
    activeCaption: "等你确认 · 确认后才会开工",
    resumeLead: "团队尚未开工。等待你确认后才会上场，请过目分工：",
    resumeCta: "授权并开工",
    notePlaceholder: "可选 · 对全体队员的嘱咐（授权开工时注入）",
    resolved: {
      continue: {
        icon: Check,
        label: "已授权开工 · 首波已放行",
      },
      adjust: {
        icon: Pencil,
        label: "已调整 · 备注已注入队员并开做",
      },
      stop: { icon: OctagonX, label: "已停止 · 团队未启动" },
      // research_first 仅辩论开工卡合法；误落到 delegate 时按停止文案降级展示。
      research_first: {
        icon: OctagonX,
        label: "已停止 · 团队未启动",
      },
      timeout: { icon: Clock, label: "未及时回应，已自动开做" },
      orphaned: {
        icon: Ban,
        label: "已失效（回合已结束或服务已重启）",
      },
    },
    continueWithNote: {
      icon: Check,
      label: "已授权开工 · 嘱咐已注入队员",
    },
  },
  debate: {
    activeCaption: "等你确认 · 确认后才会开赛",
    resumeLead: "辩论尚未开赛。等待你确认后才会开赛，请过目辩题与立场：",
    resumeCta: "授权开赛",
    notePlaceholder: "可选 · 开赛嘱咐（如你最关心的争议点），授权开赛时注入",
    resolved: {
      continue: {
        icon: Check,
        label: "已授权开赛 · 辩论已放行",
      },
      // 历史 adjust 消息保留原渲染文案（旧「改辩题」语义）；新路径不再发 adjust。
      adjust: {
        icon: Pencil,
        label: "已调整辩题 · 开赛",
      },
      stop: { icon: OctagonX, label: "已停止 · 辩论未开赛" },
      research_first: {
        icon: Scale,
        label: "已选先调研 · 辩论未开赛",
      },
      timeout: { icon: Clock, label: "未及时回应，已自动开赛" },
      orphaned: {
        icon: Ban,
        label: "已失效（回合已结束或服务已重启）",
      },
    },
    continueWithNote: {
      icon: Check,
      label: "已授权开赛 · 嘱咐已注入",
    },
  },
} as const satisfies Record<KickoffPrimitive, TeamPrimitiveMeta>;

export type TeamResolvedOutcome = TeamResolvedRow;

export function teamResolvedOutcome(
  primitive: KickoffPrimitive,
  decision: CheckpointDecision,
  hasNote: boolean,
): TeamResolvedOutcome {
  const table = TEAM_PRIMITIVE_META[primitive];
  // Historical `per_call` resolves collapse to continue copy (UI no longer offers it).
  const resolvedKey = decision === "per_call" ? "continue" : decision;
  if (decision === "continue" && hasNote) {
    return table.continueWithNote;
  }
  return (
    table.resolved[resolvedKey as keyof typeof table.resolved] ??
    table.resolved.continue
  );
}

export function teamPendingMarkerLabel(
  primitive: KickoffPrimitive,
  summarySuffix: string,
): string {
  return `${TEAM_PRIMITIVE_META[primitive].activeCaption}（${summarySuffix}）`;
}
