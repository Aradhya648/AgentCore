import { ApiError } from "@/services/api";
import { resolveInteraction } from "@/services/interaction";
import type { ResolveInteractionBody } from "@/services/interaction";
import type { PlanReviewUserDecision } from "@/services/planReview";
import { runResume } from "@/services/turns";
import { useComposerDraftStore } from "@/stores/composer";
import {
  INTERACTION_SUBMIT_PATH,
  useInteractionStore,
} from "@/stores/interactions";
import type { InteractionKind } from "@/types/interactionExt";

/** True when the API says this interaction is no longer answerable. */
export function isInteractionOrphanedError(err: unknown): boolean {
  if (!(err instanceof ApiError)) return false;
  if (err.status !== 410) return false;
  if (err.code === "interaction_orphaned") return true;
  // FastAPI detail={code:...} body shape
  try {
    const parsed = JSON.parse(err.body) as {
      detail?: { code?: string } | string;
    };
    if (
      typeof parsed.detail === "object" &&
      parsed.detail?.code === "interaction_orphaned"
    ) {
      return true;
    }
  } catch {
    /* ignore */
  }
  return false;
}

export function isPendingInteractionsAwaitingError(err: unknown): boolean {
  if (!(err instanceof ApiError) && !(err && typeof err === "object"))
    return false;
  const status =
    err instanceof ApiError
      ? err.status
      : "status" in err
        ? Number((err as { status?: number }).status)
        : undefined;
  const code =
    err instanceof ApiError
      ? err.code
      : "code" in err
        ? String((err as { code?: string }).code ?? "")
        : undefined;
  if (status === 409 && code === "pending_interactions_awaiting") return true;
  if (err instanceof ApiError) {
    try {
      const parsed = JSON.parse(err.body) as {
        detail?: { code?: string };
        error?: { code?: string };
      };
      const detailCode =
        typeof parsed.detail === "object" ? parsed.detail?.code : undefined;
      return (
        err.status === 409 &&
        (detailCode === "pending_interactions_awaiting" ||
          parsed.error?.code === "pending_interactions_awaiting")
      );
    } catch {
      return false;
    }
  }
  return false;
}

export const PENDING_INTERACTIONS_HINT =
  "有待拍板的确认卡，先处理或停止当前任务";

/** User-visible copy when submitInteraction returns a non-ok status. */
export function submitInteractionFeedback(
  result: Exclude<Awaited<ReturnType<typeof submitInteraction>>, "ok">,
): string {
  return result === "orphaned" ? "确认已失效" : "请稍候再试";
}

export type HotSubmitBody = ResolveInteractionBody;

export interface ColdSubmitArgs {
  messageId: string;
  decision: PlanReviewUserDecision;
  note: string;
  selected?: string[];
  /** Structured website style pick (s0/s1/…); preferred resume wire. */
  styleId?: string | null;
  /** Structured presentation format pick (f0/f1/…); preferred resume wire. */
  formatId?: string | null;
}

/**
 * Unified submit path (方案 §3.2): kind → cold | hot | compose.
 *
 * Hot: interactions.beginSubmit gates double-submit.
 * Cold: authority is pausedTurns (backend recovery keeps cold in `paused`, not
 * pending_interactions). Do not gate on an interactions entry — after recovery
 * there often is none. Optional best-effort status flip when an entry exists.
 * Dedup = caller local submitting + paused frame still present.
 */
export async function submitInteraction(args: {
  id: string;
  kind: InteractionKind;
  conversationId: string;
  hotBody?: HotSubmitBody;
  cold?: ColdSubmitArgs;
  /** question_posted: text to drop into the composer. */
  composeText?: string;
}): Promise<"ok" | "orphaned" | "busy"> {
  const path = INTERACTION_SUBMIT_PATH[args.kind];
  const store = useInteractionStore.getState();

  if (path === "compose") {
    const text =
      args.composeText ??
      (typeof store.get(args.id)?.payload.question === "string"
        ? String(store.get(args.id)?.payload.question)
        : "");
    if (text) useComposerDraftStore.getState().fill(text, "replace");
    store.markResolved({ kind: args.kind, id: args.id });
    return "ok";
  }

  if (path === "hot") {
    if (!store.beginSubmit(args.id)) return "busy";
    try {
      if (!args.hotBody) {
        store.reopen(args.id);
        throw new Error("缺少热路提交体");
      }
      await resolveInteraction(args.conversationId, args.id, args.hotBody);
      // Optimistic resolved; matching *_resolved SSE is idempotent.
      // Keep hotBody as resolution so grant_delegation / decision UI can read it
      // before the resolved SSE arrives.
      store.markResolved({
        kind: args.kind,
        id: args.id,
        resolution: args.hotBody as unknown as Record<string, unknown>,
      });
      return "ok";
    } catch (err) {
      if (isInteractionOrphanedError(err)) {
        store.markOrphaned(args.id);
        return "orphaned";
      }
      // Legacy 404 on hot path: treat as orphaned (假卡) rather than silent remove.
      if (err instanceof ApiError && err.status === 404) {
        store.markOrphaned(args.id);
        return "orphaned";
      }
      store.reopen(args.id);
      throw err;
    }
  }

  // cold — never gate on interactions presence
  if (!args.cold) {
    throw new Error("缺少冷路提交参数");
  }
  const tracked = store.get(args.id)?.status === "pending";
  if (tracked) store.beginSubmit(args.id);

  try {
    await runResume(
      args.cold.messageId,
      args.cold.decision,
      args.cold.note,
      args.cold.selected,
      args.cold.styleId,
      args.cold.formatId,
    );
    store.markResolved({
      kind: args.kind,
      id: args.id,
      resolution: {
        decision: args.cold.decision,
        note: args.cold.note,
        selected: args.cold.selected ?? [],
        style_id: args.cold.styleId ?? null,
        format_id: args.cold.formatId ?? null,
      },
    });
    return "ok";
  } catch (err) {
    if (isInteractionOrphanedError(err)) {
      store.markOrphaned(args.id);
      return "orphaned";
    }
    if (tracked) store.reopen(args.id);
    throw err;
  }
}
