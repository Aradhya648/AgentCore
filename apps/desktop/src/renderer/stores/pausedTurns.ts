import { toCeoReview } from "@/lib/ceoReview";
import { parseCheckpointIntent } from "@/lib/checkpointIntent";
import type { components } from "@/types/api.generated";
import type {
  AskAssumption,
  AskOption,
  AskQuestion,
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
 * (`question` + `assumptions` / `questions`).
 * The unused set is empty for the other kind.
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
    form?: string;
    write_capability?: "text_only" | "can_write_files";
    write_capability_label?: string;
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
    model?: string;
    origin?: "platform" | "byok";
    provider_id?: string;
  }>;
  maxRounds: number;
  thorough: boolean;
  /** Phase 3：裁判模型；缺省不展示跨模型署名。 */
  moderatorModel?: string;
  moderatorOrigin?: "platform" | "byok";
  moderatorProviderId?: string;
  /** Phase 3：同模型降级明示。 */
  sameModelDebate?: boolean;
  /** §7.5 D：消歧候选目录行。 */
  modelCandidates?: Array<{
    model: string;
    origin: "platform" | "byok";
    provider_id?: string;
    label?: string;
    side_key?: string;
  }>;
  /** ask_user: the framing / opening line (always shown). */
  question: string;
  /** ask_user: optional supporting background for the question. */
  context: string;
  /** ask_user: 起步计划 read-only chips (低影响决策，开场常见). */
  assumptions: AskAssumption[];
  /** ask_user: the askable items (途中岔路通常一个；开场可多个). */
  questions: AskQuestion[];
  /** ask_user: wire may still send kickoff; UI treats as generic clarification. */
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
      ...(typeof row.form === "string" && row.form ? { form: row.form } : {}),
      ...(row.write_capability === "text_only" ||
      row.write_capability === "can_write_files"
        ? {
            write_capability: row.write_capability as
              | "text_only"
              | "can_write_files",
          }
        : {}),
      ...(typeof row.write_capability_label === "string" &&
      row.write_capability_label
        ? { write_capability_label: row.write_capability_label }
        : {}),
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
          ...(typeof row.model === "string" && row.model.trim()
            ? { model: row.model }
            : {}),
          ...(row.origin === "platform" || row.origin === "byok"
            ? { origin: row.origin as "platform" | "byok" }
            : {}),
          ...(typeof row.provider_id === "string" && row.provider_id
            ? { provider_id: row.provider_id }
            : {}),
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
          ...(obj.action === "open_local_project" ||
          obj.action === "bind_local_folder" ||
          obj.action === "grant_readonly_folder" ||
          obj.action === "grant_organize_folder"
            ? {
                action: obj.action as
                  | "open_local_project"
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
  // REST 快照尚未列 moderator_* 进 schema；可选字段宽松读（absent → 不透传）。
  const moderatorModel = (s as { moderator_model?: unknown }).moderator_model;
  const moderatorOrigin = (s as { moderator_origin?: unknown })
    .moderator_origin;
  const moderatorProviderId = (s as { moderator_provider_id?: unknown })
    .moderator_provider_id;
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
    ...(typeof moderatorModel === "string" && moderatorModel.trim()
      ? { moderatorModel }
      : {}),
    ...(moderatorOrigin === "platform" || moderatorOrigin === "byok"
      ? { moderatorOrigin }
      : {}),
    ...(typeof moderatorProviderId === "string" && moderatorProviderId
      ? { moderatorProviderId }
      : {}),
    ...((s as { same_model_debate?: unknown }).same_model_debate
      ? { sameModelDebate: true }
      : {}),
    ...(() => {
      const raw = (s as { model_candidates?: unknown }).model_candidates;
      if (!Array.isArray(raw) || raw.length === 0) return {};
      const modelCandidates = raw
        .filter(
          (c): c is Record<string, unknown> =>
            !!c &&
            typeof c === "object" &&
            typeof (c as { model?: unknown }).model === "string",
        )
        .map((c) => {
          const origin =
            c.origin === "platform" || c.origin === "byok"
              ? c.origin
              : ("platform" as const);
          return {
            model: String(c.model),
            origin: origin as "platform" | "byok",
            ...(typeof c.provider_id === "string" && c.provider_id
              ? { provider_id: c.provider_id }
              : {}),
            ...(typeof c.label === "string" && c.label
              ? { label: c.label }
              : {}),
            ...(typeof c.side_key === "string" && c.side_key
              ? { side_key: c.side_key }
              : {}),
          };
        });
      return modelCandidates.length > 0 ? { modelCandidates } : {};
    })(),
    question: s.question ?? "",
    context: s.context ?? "",
    assumptions: toAssumptions(s.assumptions),
    questions: toQuestions(s.questions),
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
