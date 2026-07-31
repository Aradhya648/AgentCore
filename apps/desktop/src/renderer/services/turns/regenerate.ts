import { bumpConversationCache } from "@/hooks/useConversations";
import {
  StreamError,
  describeStreamError,
  isRetriableStreamError,
  streamErrorAction,
} from "@/lib/errors";
import type { PlanReviewUserDecision } from "@/services/planReview";
import {
  isClientOnlyResumeKey,
  resolveResumeMessageId,
} from "@/services/resume";
import { clearSidecarHealth, probeSidecar } from "@/services/sidecarHealth";
import { resolveSidecarRoot } from "@/services/sidecarRouting";
import {
  regenerateConversation,
  resumeConversation,
} from "@/services/streamConversation";
import { resumeConversationViaSidecar } from "@/services/streamConversationViaSidecar";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beginTurnPreflight } from "@/stores/conversation/turnPhaseActions";
import { clearInteractionPrompts } from "@/stores/interactionPrompts";
import { usePausedTurnStore } from "@/stores/pausedTurns";
import type { PendingResume } from "@/stores/pausedTurns";
import {
  finalizeGeneratingForPausedConversation,
  finalizeGeneratingIfNeeded,
  isAbort,
  isTransportDrop,
} from "./helpers";
import { rejoinLiveTurn } from "./recovery";

/** Durable resume routes to the local sidecar engine when the frame lives there. */
function shouldResumeViaSidecar(pending: PendingResume | undefined): boolean {
  return pending?.origin === "sidecar";
}

/**
 * Resume request was refused before any SSE opened (404/409/410/5xx, or sidecar
 * never started). Caller should restore the optimistic-removed resume card.
 * Mid-stream drops / user abort are NOT refusals — the turn may already be running.
 */
function isResumeRequestRefused(err: unknown): boolean {
  if (!(err instanceof StreamError)) return false;
  if (err.kind === "http" && err.status != null) {
    const s = err.status;
    return s === 404 || s === 409 || s === 410 || s >= 500;
  }
  return err.kind === "sidecar" && err.recoverable === true;
}

/**
 * Re-run a turn from an existing (persisted) user message.
 *
 * Backs the message-level regenerate / edit-and-resend actions, and the retry
 * path once a send has been persisted. Drops everything after the user message,
 * opens a fresh assistant bubble, then streams the new reply; the backend
 * truncates the same range so persisted history stays consistent. On a transport
 * failure it raises a retry banner that re-runs the same regenerate.
 */
export async function runRegenerate(
  userMessageId: string,
  content?: string,
): Promise<void> {
  const store = useConversationStore.getState();
  const conversationId = store.currentConversationId;
  if (!conversationId || getRuntime(conversationId).isGenerating) return;

  // Route every turn write to this conversation's slice by id, not the active
  // key — the user may switch away mid-stream and the turn keeps running in the
  // background (switchConversation no longer aborts it).
  store.clearError(conversationId);
  bumpConversationCache(conversationId);
  store.truncateAfter(userMessageId, conversationId);
  store.createAssistantMessage(conversationId);

  const ac = new AbortController();
  store.setAbort(ac, conversationId);
  beginTurnPreflight(conversationId);
  try {
    await regenerateConversation({
      conversationId,
      messageId: userMessageId,
      content,
      signal: ac.signal,
    });
  } catch (err) {
    if (isAbort(err)) {
      finalizeGeneratingIfNeeded(conversationId);
      return;
    }
    // A mid-stream drop no longer means the turn died (1a: it runs detached) —
    // rejoin it live (1b) rather than regenerating, which would double-run it.
    if (isTransportDrop(err) && (await rejoinLiveTurn(conversationId))) return;
    finalizeGeneratingIfNeeded(conversationId);
    // A failed turn never delivers `approval_resolved`; drop this conversation's
    // paused prompt (other conversations keep theirs).
    clearInteractionPrompts(conversationId);
    const msg = describeStreamError(err);
    if (msg) {
      const retry = isRetriableStreamError(err)
        ? () => void runRegenerate(userMessageId, content)
        : null;
      useConversationStore
        .getState()
        .setError(msg, retry, conversationId, streamErrorAction(err));
    }
  } finally {
    useConversationStore.getState().setAbort(null, conversationId);
  }
}

/**
 * Continue a durably-paused turn (结构化挂起 2b resume) and stream the continuation.
 *
 * The turn paused at a plan_review / ask_user checkpoint and was persisted, then
 * lost its live stream (disconnect / restart). The user's decision (continue /
 * adjust / stop) — plus any ask_user option `selected` — is POSTed to the resume
 * endpoint, which claims the frame and drives the rest of the turn on a fresh SSE.
 * No new user message — resume reuses the paused assistant bubble (same turn id /
 * projection key).
 *
 * Card lifecycle: remove the resume card as soon as the request is about to fire;
 * restore it only when the request is refused before any stream opens (404/409/410/
 * 5xx / sidecar never started). Mid-stream interrupt and user abort leave the card
 * gone (the turn is already running — reconnect / banner paths handle that).
 *
 * Sidecar frames never degrade to cloud resume (双模式工作区 §10.4 — cloud has no
 * local frame → guaranteed 404). Missing sidecar target or failed probe keeps the
 * card and raises a retry banner.
 */
export async function runResume(
  messageId: string,
  decision: PlanReviewUserDecision,
  note: string,
  selected: string[] = [],
  styleId: string | null | undefined = null,
  formatId: string | null | undefined = null,
): Promise<void> {
  const store = useConversationStore.getState();
  const conversationId = store.currentConversationId;
  if (!conversationId) {
    throw new Error("resume blocked: no active conversation");
  }
  if (getRuntime(conversationId).isGenerating) {
    // Defense: cold pending card + stuck generating is illegal — clear then continue.
    // True mid-stream (no cold card) still blocks so ResumePrompt submitting resets.
    const hasColdPending = usePausedTurnStore
      .getState()
      .pending.some((p) => p.conversationId === conversationId);
    if (hasColdPending) {
      finalizeGeneratingForPausedConversation(conversationId);
    } else {
      store.setError(
        "当前回合仍在生成中，请稍后再点继续",
        null,
        conversationId,
        null,
      );
      throw new Error("resume blocked: turn is still generating");
    }
  }

  store.clearError(conversationId);
  bumpConversationCache(conversationId);

  // Card may still key a client bubble id while the bubble already has a stamp —
  // rekey to the server id before pending lookup / POST (only truly unstamped
  // keys hit isClientOnlyResumeKey below).
  const resumeMessageId = resolveResumeMessageId(conversationId, messageId);

  // Capture the pending frame BEFORE removing it — sidecar path needs its
  // original user message text / pinned user bubble id; refuse path restores it.
  const sidecarTarget = await resolveSidecarRoot(conversationId);
  const pending = usePausedTurnStore
    .getState()
    .pending.find((p) => p.messageId === resumeMessageId);
  const viaSidecar = shouldResumeViaSidecar(pending);

  /** Banner「重试」：错误已在 runResume 内 setError；吞掉 rejection 避免未处理 Promise。 */
  const retryResume = () => {
    void runResume(
      resumeMessageId,
      decision,
      note,
      selected,
      styleId,
      formatId,
    ).catch(() => {});
  };

  const raiseSidecarUnavailable = (detail: string | null) => {
    store.setError(
      detail
        ? `${detail}，本地引擎暂不可用，无法继续这次暂停的回合，请稍后重试`
        : "本地引擎暂不可用，无法继续这次暂停的回合，请稍后重试",
      // 手动重试 = 用户「我修好环境了，再试一次」——先清会话级健康缓存强制重探，
      // 否则重试必命中刚记下的 bad 缓存、变成死按钮。
      () => {
        clearSidecarHealth();
        retryResume();
      },
      conversationId,
      null,
    );
  };

  // A paused sidecar frame lives ONLY on this machine — never degrade to cloud
  // (cloud has no such frame → guaranteed 404). No local target → keep card + banner.
  // Throw so callers (submitInteraction) do not markResolved on a silent early exit.
  if (viaSidecar && !sidecarTarget) {
    raiseSidecarUnavailable(null);
    throw new Error("resume blocked: sidecar unavailable");
  }

  // Probe first: if the env can't start, keep the resume card and raise a retry
  // banner — never a guaranteed-404 cloud resume.
  if (viaSidecar && sidecarTarget) {
    const probe = await probeSidecar(sidecarTarget);
    if (!probe.healthy) {
      raiseSidecarUnavailable(probe.detail);
      throw new Error("resume blocked: sidecar probe failed");
    }
  }

  if (isClientOnlyResumeKey(conversationId, resumeMessageId)) {
    store.setError(
      "续跑键无效（缺少服务端消息 ID），无法继续这次暂停的回合，请稍后重试",
      retryResume,
      conversationId,
      null,
    );
    throw new Error("resume blocked: client-only message id");
  }

  // Same-turn continuation: flip the paused assistant back to streaming.
  // Reload race: bubble may be missing → fall back to a fresh streaming slot.
  const resumed = store.resumePausedAssistant(resumeMessageId, conversationId);
  if (!resumed) {
    store.createAssistantMessage(conversationId);
    store.setServerMessageIdOnLastMessage(resumeMessageId, conversationId);
  }

  // Optimistic: drop the card as the request fires. Restore only on pre-stream refusal.
  const pendingSnapshot = pending;
  usePausedTurnStore.getState().remove(resumeMessageId);

  const ac = new AbortController();
  store.setAbort(ac, conversationId);
  beginTurnPreflight(conversationId);
  try {
    if (viaSidecar && pendingSnapshot && sidecarTarget) {
      const userMessageId =
        pendingSnapshot.userMessageId ||
        [...getRuntime(conversationId).messages]
          .reverse()
          .find((m) => m.role === "user")?.id ||
        "";
      await resumeConversationViaSidecar({
        conversationId,
        rootId: sidecarTarget.rootId,
        subpath: sidecarTarget.subpath,
        messageId: resumeMessageId,
        decision,
        note,
        selected,
        styleId: styleId ?? undefined,
        formatId: formatId ?? undefined,
        userMessage: pendingSnapshot.userMessage,
        userMessageId,
        signal: ac.signal,
      });
    } else {
      await resumeConversation({
        conversationId,
        messageId: resumeMessageId,
        decision,
        note,
        selected,
        styleId: styleId ?? undefined,
        formatId: formatId ?? undefined,
        signal: ac.signal,
      });
    }
  } catch (err) {
    if (isAbort(err)) {
      return;
    }
    // A mid-stream drop no longer means the turn died (1a: it runs detached) —
    // rejoin it live (1b) rather than re-resuming, which would double-run it.
    // Do NOT restore the resume card — the turn is already running server-side.
    if (isTransportDrop(err) && (await rejoinLiveTurn(conversationId))) {
      return;
    }
    // Request refused before any stream opened → put the card back for retry.
    if (isResumeRequestRefused(err) && pendingSnapshot) {
      usePausedTurnStore.getState().addLiveResume(pendingSnapshot);
    }
    const s = useConversationStore.getState();
    if (getRuntime(conversationId).isGenerating) {
      s.finalizeLastMessage(conversationId);
    }
    // A failed turn never delivers `approval_resolved`; drop this conversation's
    // paused prompt (other conversations keep theirs).
    clearInteractionPrompts(conversationId);
    const msg = describeStreamError(err);
    if (msg) {
      const retry = isRetriableStreamError(err) ? retryResume : null;
      s.setError(msg, retry, conversationId, streamErrorAction(err));
    }
    // Re-throw so submitInteraction does not markResolved (假成功).
    throw err;
  } finally {
    useConversationStore.getState().setAbort(null, conversationId);
  }
}
