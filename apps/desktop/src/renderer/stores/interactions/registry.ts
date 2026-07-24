/**
 * Single registration table for user-facing decision / ask interactions.
 *
 * Wire shape (required/resolved event + id field) comes from codegen
 * (`INTERACTION_KIND_WIRE`). This module adds desktop-only metadata:
 * submit path, timeline marker, SSE side-effects. Card components / cold
 * resume renderers live in `registryUi.tsx` to keep this file React-free.
 *
 * Adding a new decision card = one row here (+ UI binding) instead of
 * parallel switches across types / store maps / SSE / fold / timeline.
 */

import {
  INTERACTION_KIND_WIRE,
  type UserInteractionKind,
} from "@agentcore/contract-types";

export type InteractionKind = UserInteractionKind;

export type InteractionSubmitPath = "cold" | "hot" | "compose" | "stage";

/** Process-step discriminant stamped into the CEO message lane. */
export type TimelineProcessKind =
  | "checkpoint"
  | "ask"
  | "plan_review"
  | "team_preview"
  | "escalation"
  | "approval"
  | "delegation_authorization"
  | "stage_card";

export interface TimelineMarkerDef {
  processKind: TimelineProcessKind;
  /** Id field on the ProcessStep wire shape. */
  stepIdField:
    | "checkpoint_id"
    | "ask_id"
    | "escalation_id"
    | "approval_id"
    | "authorization_id"
    | "stage_card_id";
  /** Drop trailing content into the card (blocking ask_user). */
  absorbTrailingContent?: boolean;
  /** Insert before the last `team` marker (team_preview product order). */
  insertBeforeTeam?: boolean;
}

export interface InteractionSseRequiredEffects {
  flushBuffers?: boolean;
  recordExecFrame?: boolean;
}

export interface InteractionSseResolvedEffects {
  removePausedTurn?: boolean;
  flushFrames?: boolean;
  recordExecFrame?: boolean;
}

/**
 * Where the live SSE pair is dispatched. Escalation frames ride the execution
 * handler (team projection); everything else uses the interaction handler.
 */
export type InteractionSseVia = "interaction" | "execution";

export interface InteractionKindDef {
  kind: InteractionKind;
  submitPath: InteractionSubmitPath;
  timeline?: TimelineMarkerDef;
  sseVia?: InteractionSseVia;
  sseRequired?: InteractionSseRequiredEffects;
  sseResolved?: InteractionSseResolvedEffects;
}

/** The registry — one row per UserInteractionKind. */
export const INTERACTION_REGISTRY: readonly InteractionKindDef[] = [
  {
    kind: "approval",
    submitPath: "hot",
    timeline: {
      processKind: "approval",
      stepIdField: "approval_id",
    },
    // Flush rAF-buffered CEO prose BEFORE stamping so the 痕迹 marker lands after
    // the same-round lead-in (mirrors the golden's [content, approval] order).
    sseRequired: { flushBuffers: true },
  },
  {
    kind: "delegation_authorization",
    submitPath: "hot",
    timeline: {
      processKind: "delegation_authorization",
      stepIdField: "authorization_id",
      // 产品修正：「放行开工」族与开工卡同锚定 —— 排协作图之前（授权 → 团队干活）。
      insertBeforeTeam: true,
    },
    sseRequired: { flushBuffers: true },
  },
  {
    kind: "escalation",
    submitPath: "hot",
    sseVia: "execution",
    timeline: {
      processKind: "escalation",
      stepIdField: "escalation_id",
    },
  },
  {
    kind: "ask_user",
    submitPath: "cold",
    timeline: {
      processKind: "checkpoint",
      stepIdField: "checkpoint_id",
      absorbTrailingContent: true,
    },
    sseRequired: { flushBuffers: true },
    sseResolved: { removePausedTurn: true },
  },
  {
    kind: "plan_review",
    submitPath: "cold",
    timeline: {
      processKind: "plan_review",
      stepIdField: "checkpoint_id",
    },
    sseRequired: { flushBuffers: true, recordExecFrame: true },
    sseResolved: {
      removePausedTurn: true,
      flushFrames: true,
      recordExecFrame: true,
    },
  },
  {
    kind: "team_preview",
    submitPath: "cold",
    timeline: {
      processKind: "team_preview",
      stepIdField: "checkpoint_id",
      insertBeforeTeam: true,
    },
    sseRequired: { flushBuffers: true },
    sseResolved: { removePausedTurn: true },
  },
  {
    kind: "question_posted",
    submitPath: "compose",
    timeline: {
      processKind: "ask",
      stepIdField: "ask_id",
    },
    sseRequired: { flushBuffers: true },
  },
  {
    kind: "stage_card",
    // 跨回合耐久卡：resolve 起新回合 SSE（非 cold resume / 非 hot Future）。
    submitPath: "stage",
    timeline: {
      processKind: "stage_card",
      stepIdField: "stage_card_id",
    },
    sseRequired: { flushBuffers: true },
  },
] as const;

// ── Derived indexes (no parallel hand maps) ─────────────────────────────

function buildByKind(): Record<InteractionKind, InteractionKindDef> {
  const out = {} as Record<InteractionKind, InteractionKindDef>;
  for (const def of INTERACTION_REGISTRY) {
    out[def.kind] = def;
  }
  return out;
}

export const INTERACTION_BY_KIND: Record<InteractionKind, InteractionKindDef> =
  buildByKind();

export const INTERACTION_SUBMIT_PATH: Record<
  InteractionKind,
  InteractionSubmitPath
> = Object.fromEntries(
  INTERACTION_REGISTRY.map((d) => [d.kind, d.submitPath]),
) as Record<InteractionKind, InteractionSubmitPath>;

export const INTERACTION_ID_FIELD: Record<InteractionKind, string> =
  Object.fromEntries(
    (
      Object.entries(INTERACTION_KIND_WIRE) as Array<
        [InteractionKind, { idField: string }]
      >
    ).map(([kind, wire]) => [kind, wire.idField]),
  ) as Record<InteractionKind, string>;

const REQUIRED_EVENT_TO_KIND = new Map<string, InteractionKind>();
const RESOLVED_EVENT_TO_KIND = new Map<string, InteractionKind>();
const TIMELINE_BY_PROCESS = new Map<TimelineProcessKind, InteractionKindDef>();

for (const def of INTERACTION_REGISTRY) {
  const wire = INTERACTION_KIND_WIRE[def.kind];
  REQUIRED_EVENT_TO_KIND.set(wire.requiredEvent, def.kind);
  if (wire.resolvedEvent) {
    RESOLVED_EVENT_TO_KIND.set(wire.resolvedEvent, def.kind);
  }
  if (def.timeline) {
    TIMELINE_BY_PROCESS.set(def.timeline.processKind, def);
  }
}

export function kindFromRequiredEvent(
  eventType: string,
): InteractionKind | null {
  return REQUIRED_EVENT_TO_KIND.get(eventType) ?? null;
}

export function kindFromResolvedEvent(
  eventType: string,
): InteractionKind | null {
  return RESOLVED_EVENT_TO_KIND.get(eventType) ?? null;
}

export function defFromRequiredEvent(
  eventType: string,
): InteractionKindDef | null {
  const kind = kindFromRequiredEvent(eventType);
  return kind ? INTERACTION_BY_KIND[kind] : null;
}

export function defFromResolvedEvent(
  eventType: string,
): InteractionKindDef | null {
  const kind = kindFromResolvedEvent(eventType);
  return kind ? INTERACTION_BY_KIND[kind] : null;
}

export function defFromTimelineProcess(
  processKind: TimelineProcessKind,
): InteractionKindDef | null {
  return TIMELINE_BY_PROCESS.get(processKind) ?? null;
}

export function wireFor(kind: InteractionKind) {
  return INTERACTION_KIND_WIRE[kind];
}

/** Interaction-channel SSE event types (excludes escalation → execution handler). */
export function interactionChannelEventTypes(): ReadonlySet<string> {
  const out = new Set<string>();
  for (const def of INTERACTION_REGISTRY) {
    if ((def.sseVia ?? "interaction") !== "interaction") continue;
    const wire = INTERACTION_KIND_WIRE[def.kind];
    out.add(wire.requiredEvent);
    if (wire.resolvedEvent) out.add(wire.resolvedEvent);
  }
  return out;
}
