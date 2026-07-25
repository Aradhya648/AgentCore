import { purgeConversationRuntimeState } from "@/lib/purgeConversationRuntimeState";
import { dispatchSSEEvent, flushPendingContent } from "@/services/sse/dispatch";
import { useConversationStore } from "@/stores/conversation";
import { enterTurnStreaming } from "@/stores/conversation/turnPhaseActions";
import { useExecutionStore } from "@/stores/execution";
import type { SSEEvent } from "@/types/events";
import { type FoldReplaySource, foldEventsFrom } from "./source";

/**
 * Replay a recorded SSE event stream into a conversation slice so the real chat UI
 * renders the resulting AI state — zero backend, zero LLM, zero token cost. This
 * mirrors the production live path (`pumpSSE` → `dispatchSSEEvent`), so what shows
 * up is exactly what a real turn produces; the events are the same golden vectors
 * the conformance gate runs, so the preview can never drift from production.
 *
 * 消费端 A（FOLD）：经 `preview/source` 读超集文档；永不 remint；缺 pacing 忽略。
 * 禁止与 B（服务端 sink）对同一会话双注入。
 */

type FoldInput = FoldReplaySource | SSEEvent[];

function seedSlice(conversationId: string, userPrompt?: string): void {
  const store = useConversationStore.getState();
  // Fresh slice each time so re-playing the same fixture starts clean.
  store.dropConversationRuntime(conversationId);
  // Align delete-conversation cleanup: pausedTurns + InteractionStore (+ siblings).
  // Without clearing interactions, re-replay / frame scrub stacks stale stage_card /
  // approval entries from the prior run (shoot 假绿 / Dock 叠卡).
  purgeConversationRuntimeState(conversationId);
  // Execution frames key by the vector's FIXED server message id, so a re-replay
  // (StrictMode double-invoke) would APPEND a second copy of every frame — doubling
  // worker output text and escalation cards. The preview page hosts one fixture at a
  // time, so dropping the whole map is safe and keeps re-replays idempotent.
  useExecutionStore.setState({ byId: {} });
  store.switchConversation(conversationId);
  if (userPrompt) {
    store.addMessage(
      {
        id: crypto.randomUUID(),
        role: "user",
        content: userPrompt,
        createdAt: new Date().toISOString(),
        executionId: null,
        isStreaming: false,
      },
      conversationId,
    );
  }
  // 离线回放无真实开流门闩：把 phase 推到 streaming，否则 ensureStreamingAssistant
  // / 内容合批在 idle 下拒建助手气泡（turnPhase 门禁）。message_end 仍会 completeTurnPhase。
  enterTurnStreaming(conversationId);
}

/** Replay the whole stream at once → the turn's terminal AI state. */
export function replayFixtureNow(
  conversationId: string,
  input: FoldInput,
  userPrompt?: string,
): void {
  const events = foldEventsFrom(input);
  seedSlice(conversationId, userPrompt);
  for (const event of events) {
    dispatchSSEEvent(event, { conversationId, source: "server" });
  }
  // content_delta is rAF-buffered and a paused fixture never emits message_end, so
  // flush to land the final text on the bubble synchronously.
  flushPendingContent(conversationId);
}

/**
 * Replay only the first `count` events → a mid-stream (in-progress) frame, e.g.
 * a tool still running or a run started-but-not-completed. Drives the screenshot
 * harness's frame scrubber and the `#/preview?s=…&k=<count>` deep link, so the
 * streaming intermediate states are eyeball-able and gate-able, not just terminal.
 */
export function replayFixturePrefix(
  conversationId: string,
  input: FoldInput,
  count: number,
  userPrompt?: string,
): void {
  const events = foldEventsFrom(input);
  seedSlice(conversationId, userPrompt);
  const n = Math.max(0, Math.min(count, events.length));
  for (let i = 0; i < n; i++) {
    dispatchSSEEvent(events[i], { conversationId, source: "server" });
  }
  // content_delta is rAF-buffered; flush so a paused mid-stream frame lands its
  // partial text synchronously before the harness screenshots.
  flushPendingContent(conversationId);
}

/**
 * Replay with a per-event delay so the turn animates in like a live stream.
 * Returns a canceller (call on unmount / when switching fixtures).
 */
export function replayFixtureStreamed(
  conversationId: string,
  input: FoldInput,
  userPrompt?: string,
  stepMs = 28,
): () => void {
  const events = foldEventsFrom(input);
  seedSlice(conversationId, userPrompt);
  let cancelled = false;
  let timer: ReturnType<typeof setTimeout> | undefined;
  let i = 0;
  const tick = (): void => {
    if (cancelled) return;
    if (i >= events.length) {
      flushPendingContent(conversationId);
      return;
    }
    dispatchSSEEvent(events[i++], { conversationId, source: "server" });
    timer = setTimeout(tick, stepMs);
  };
  tick();
  return () => {
    cancelled = true;
    if (timer) clearTimeout(timer);
    flushPendingContent(conversationId);
  };
}
