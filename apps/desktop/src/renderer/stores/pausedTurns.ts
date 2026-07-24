import { toCeoReview } from "@/lib/ceoReview";
import { parseCheckpointIntent } from "@/lib/checkpointIntent";
import type { components } from "@/types/api.generated";
import type {
  AskAssumption,
  AskOption,
  AskQuestion,
  AskStyleOption,
  CeoReviewSummary,
  CheckpointIntent,
  PlanReviewPending,
  PlanReviewStep,
} from "@/types/events";
import { create } from "zustand";

type PausedTurnSummary = components["schemas"]["PausedTurnSummary"];
type SuspensionKind = components["schemas"]["SuspensionKind"];

/** Where the durable paused frame lives — drives resume routing in {@link runResume}. */
export type ResumeOrigin = "sidecar" | "server";

/**
 * A turn that paused at a plan_review / ask_user checkpoint, was DURABLY persisted,
 * then lost its live SSE — client disconnect / server restart (结构化挂起 2b). On
 * conversation reopen the client loads these from the recovery snapshot (GET /recovery)
 * and offers 继续 / 调整 / 停止, each driving POST .../resume to continue on a fresh stream.
 *
 * Mirrors the approvals store: one entry per paused turn, tagged with its
 * `conversationId` so several conversations can each hold their own pending
 * resumes; the card above the composer renders only the active conversation's.
 *
 * `kind` selects the card the {@link ResumePrompt} renders: plan_review reviews the
 * finished `steps` + gated `pending`; ask_user re-asks the unified card content
 * (`question` + `assumptions` / `questions` / `styleOptions`). The unused set is
 * empty for the other kind.
 */
export interface PendingResume {
  /** The paused turn's assistant message_id — the resume key, and the id the
   * resumed reply reuses when it finally persists. */
  messageId: string;
  conversationId: string;
  checkpointId: string;
  /** Which suspend point this turn paused at — drives the resume card variant. */
  kind: SuspensionKind;
  /** The original user request that started the paused turn (for context). */
  userMessage: string;
  /** Client-minted id of the user bubble (pinned on pause write-back). */
  userMessageId: string;
  /** plan_review: the just-completed checkpoint step(s) under review. */
  steps: PlanReviewStep[];
  /** plan_review: the downstream nodes gated behind the pause. */
  pending: PlanReviewPending[];
  /** plan_review: 主 Agent 暂停前的把关摘要（absent = 旧帧 / 无摘要 → 不渲染）。 */
  ceoReview?: CeoReviewSummary;
  /** team_preview: upcoming workers before the first wave. */
  workers: Array<{
    run_id: string;
    role: string;
    task: string;
    depends_on: string[];
    debate: boolean;
  }>;
  /** team_preview (开工卡): grantable tools listed for capability auth. */
  tools: string[];
  /** team_preview: orchestration primitive discriminant. */
  primitive: "delegate" | "debate";
  /** debate kickoff: motion / form / sides / budget. */
  motion: string;
  form: string;
  sides: Array<{
    key: string;
    name: string;
    stance: string;
    is_subject?: boolean;
  }>;
  maxRounds: number;
  thorough: boolean;
  /** debate kickoff: show「先多视角调研再辩」third action (缺省 false). */
  offerResearchFirst: boolean;
  /** debate kickoff: elevate research-first as visual primary (缺省 false). */
  researchFirstRecommended: boolean;
  /** ask_user: the framing / opening line (always shown). */
  question: string;
  /** ask_user: optional supporting background for the question. */
  context: string;
  /** ask_user: 起步计划 read-only chips (低影响决策，开场常见). */
  assumptions: AskAssumption[];
  /** ask_user: the askable items (途中岔路通常一个；开场可多个). */
  questions: AskQuestion[];
  /** ask_user: 风格预设 (视觉类产物才有). */
  styleOptions: AskStyleOption[];
  /** ask_user: kickoff 开工提案 vs decision 途中拍板 — drives card copy. */
  intent: CheckpointIntent;
  /** Where the durable frame lives — drives {@link runResume} sidecar vs server routing. */
  origin: ResumeOrigin;
}

/** `steps` / `pending` arrive as loose JSON dicts (backend ``list[dict]``); map
 * them to the known display shapes, tolerating any missing field. */
const toSteps = (raw: PausedTurnSummary["steps"]): PlanReviewStep[] =>
  (raw ?? []).map((s) => ({
    run_id: String(s.run_id ?? ""),
    role: String(s.role ?? ""),
    summary: String(s.summary ?? ""),
  }));

const toPending = (raw: PausedTurnSummary["pending"]): PlanReviewPending[] =>
  (raw ?? []).map((p) => ({
    run_id: String(p.run_id ?? ""),
    role: String(p.role ?? ""),
  }));

const toWorkers = (
  raw: PausedTurnSummary["workers"] | undefined,
): PendingResume["workers"] =>
  (raw ?? []).map((w) => {
    const row = (w ?? {}) as Record<string, unknown>;
    return {
      run_id: String(row.run_id ?? ""),
      role: String(row.role ?? ""),
      task: String(row.task ?? ""),
      depends_on: Array.isArray(row.depends_on)
        ? row.depends_on.map(String)
        : [],
      debate: Boolean(row.debate),
    };
  });

const toSides = (raw: unknown): PendingResume["sides"] =>
  Array.isArray(raw)
    ? raw.map((s) => {
        const row = (s ?? {}) as Record<string, unknown>;
        return {
          key: String(row.key ?? ""),
          name: String(row.name ?? ""),
          stance: String(row.stance ?? ""),
          ...(row.is_subject ? { is_subject: true as const } : {}),
        };
      })
    : [];

const toPrimitive = (raw: unknown): PendingResume["primitive"] =>
  raw === "debate" ? "debate" : "delegate";

/** ask_user rich fields arrive as loose JSON dicts (backend ``list[dict]``); map
 * them to the typed display shapes the unified card reads, tolerating missing keys.
 * The backend already normalized + capped + id'd them (ask_user._normalize_*). */
const toAssumptions = (
  raw: PausedTurnSummary["assumptions"],
): AskAssumption[] =>
  (raw ?? []).map((a, i) => ({
    id: String(a.id ?? `a${i}`),
    label: String(a.label ?? ""),
    value: String(a.value ?? ""),
  }));

/** Options rehydrate as `{label, detail?, recommended?, action?}` from the backend. */
const toOptions = (raw: unknown): AskOption[] =>
  Array.isArray(raw)
    ? raw.map((o) => {
        const obj = (o ?? {}) as Record<string, unknown>;
        return {
          label: String(obj.label ?? ""),
          ...(obj.detail ? { detail: String(obj.detail) } : {}),
          ...(obj.recommended ? { recommended: true } : {}),
          ...(obj.action === "bind_local_folder" ||
          obj.action === "grant_readonly_folder"
            ? {
                action: obj.action as
                  | "bind_local_folder"
                  | "grant_readonly_folder"
                  | "grant_organize_folder",
              }
            : {}),
        };
      })
    : [];

const toQuestions = (raw: PausedTurnSummary["questions"]): AskQuestion[] =>
  (raw ?? []).map((q, i) => ({
    id: String(q.id ?? `q${i}`),
    prompt: String(q.prompt ?? ""),
    kind: q.kind === "text" ? "text" : "choice",
    options: toOptions(q.options),
    multiple: Boolean(q.multiple),
    default: String(q.default ?? ""),
  }));

const toIntent = (raw: unknown): CheckpointIntent => parseCheckpointIntent(raw);

const toStyleOptions = (
  raw: PausedTurnSummary["style_options"],
): AskStyleOption[] =>
  (raw ?? []).map((s, i) => ({
    id: String(s.id ?? `s${i}`),
    label: String(s.label ?? ""),
  }));

/** One recovery-frame summary tagged with where its durable frame lives. */
export type PausedTurnEntry = {
  summary: PausedTurnSummary;
  origin: ResumeOrigin;
};

interface PausedTurnState {
  pending: PendingResume[];
  /** Replace one conversation's pending resumes (from the recovery snapshot on reopen),
   * leaving other conversations' entries untouched. Each entry carries its own
   * {@link ResumeOrigin} so a mixed cloud+sidecar session routes resume correctly. */
  setForConversation: (
    conversationId: string,
    entries: PausedTurnEntry[],
  ) => void;
  /** 挂起即收口 (②): add/replace ONE turn's resume entry the moment its LIVE stream ENDS
   * at a checkpoint (message_end finish_reason=paused). Built from the *_required payload
   * already folded onto the bubble — no /recovery round-trip — so it reproduces offline in
   * #/preview. Idempotent by messageId, so a later reopen's setForConversation (the same
   * frame, re-read from the backend) simply replaces it rather than stacking a duplicate. */
  addLiveResume: (entry: PendingResume) => void;
  /** Drop one paused turn (it is being / has been resumed). Idempotent. */
  remove: (messageId: string) => void;
  /** Drop the paused turn whose checkpoint just settled on the LIVE stream
   * (checkpoint_resolved / plan_review_resolved). The server deletes the durable
   * frame on an in-process resolve, so mirror that here — otherwise a 待恢复 card
   * left over from a duplicate surface lingers and 404s when clicked (its frame is
   * already gone). Keyed by checkpoint_id (what the resolve event carries).
   * Idempotent; a no-op when no entry matches. */
  removeByCheckpoint: (checkpointId: string) => void;
  /** Forget pending resumes. Pass a conversationId to drop only that
   * conversation's; omit for a full reset (e.g. logout / tests). */
  clear: (conversationId?: string) => void;
  /** Re-key a live-surfaced frame after message_start stamps the server id
   * (card may have been keyed by the client bubble id when pause raced stamp). */
  rekeyMessageId: (fromMessageId: string, toMessageId: string) => void;
}

function entryFromSummary(
  conversationId: string,
  s: PausedTurnSummary,
  origin: ResumeOrigin,
): PendingResume {
  return {
    messageId: s.message_id,
    conversationId,
    checkpointId: s.checkpoint_id,
    kind: s.kind,
    userMessage: s.user_message ?? "",
    userMessageId: s.user_message_id ?? "",
    steps: toSteps(s.steps),
    pending: toPending(s.pending),
    // REST 快照尚未列该字段进 schema；宽松读，后端带了就透传（absent → undefined）。
    ceoReview: toCeoReview((s as { ceo_review?: unknown }).ceo_review),
    workers: toWorkers(s.workers),
    tools: Array.isArray((s as { tools?: unknown }).tools)
      ? ((s as { tools: unknown[] }).tools.filter(
          (t): t is string => typeof t === "string",
        ) as string[])
      : [],
    primitive: toPrimitive((s as { primitive?: unknown }).primitive),
    motion: String((s as { motion?: unknown }).motion ?? ""),
    form: String((s as { form?: unknown }).form ?? ""),
    sides: toSides((s as { sides?: unknown }).sides),
    maxRounds: Number((s as { max_rounds?: unknown }).max_rounds ?? 0),
    thorough: (s as { thorough?: unknown }).thorough !== false,
    offerResearchFirst: Boolean(
      (s as { offer_research_first?: unknown }).offer_research_first,
    ),
    researchFirstRecommended: Boolean(
      (s as { research_first_recommended?: unknown })
        .research_first_recommended,
    ),
    question: s.question ?? "",
    context: s.context ?? "",
    assumptions: toAssumptions(s.assumptions),
    questions: toQuestions(s.questions),
    styleOptions: toStyleOptions(s.style_options),
    intent: toIntent((s as { intent?: unknown }).intent),
    origin,
  };
}

export const usePausedTurnStore = create<PausedTurnState>((set) => ({
  pending: [],

  setForConversation: (conversationId, entries) =>
    set((state) => {
      const others = state.pending.filter(
        (p) => p.conversationId !== conversationId,
      );
      const existing = state.pending.filter(
        (p) => p.conversationId === conversationId,
      );
      // Empty recovery must not wipe live-surfaced frames (open race: pause
      // lands / surfaces before durable snapshot catches up). Non-empty recovery
      // still replaces so reopen stays authoritative.
      if (entries.length === 0 && existing.length > 0) {
        return state;
      }
      return {
        pending: [
          ...others,
          ...entries.map(({ summary, origin }) =>
            entryFromSummary(conversationId, summary, origin),
          ),
        ],
      };
    }),

  addLiveResume: (entry) =>
    set((state) => ({
      pending: [
        ...state.pending.filter((p) => p.messageId !== entry.messageId),
        entry,
      ],
    })),

  remove: (messageId) =>
    set((state) => ({
      pending: state.pending.filter((p) => p.messageId !== messageId),
    })),

  removeByCheckpoint: (checkpointId) =>
    set((state) => {
      const pending = state.pending.filter(
        (p) => p.checkpointId !== checkpointId,
      );
      return pending.length === state.pending.length ? state : { pending };
    }),

  clear: (conversationId) =>
    set((state) =>
      conversationId === undefined
        ? { pending: [] }
        : {
            pending: state.pending.filter(
              (p) => p.conversationId !== conversationId,
            ),
          },
    ),

  rekeyMessageId: (fromMessageId, toMessageId) =>
    set((state) => {
      if (!fromMessageId || !toMessageId || fromMessageId === toMessageId) {
        return state;
      }
      let changed = false;
      const pending = state.pending.map((p) => {
        if (p.messageId !== fromMessageId) return p;
        changed = true;
        return { ...p, messageId: toMessageId };
      });
      if (!changed) return state;
      // Drop duplicates if recovery already keyed the server id.
      const seen = new Set<string>();
      const deduped: PendingResume[] = [];
      for (const p of pending) {
        if (seen.has(p.messageId)) continue;
        seen.add(p.messageId);
        deduped.push(p);
      }
      return { pending: deduped };
    }),
}));
