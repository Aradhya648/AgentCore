import { surfaceResumeFromLiveTurn } from "@/services/resume";
import { traceTurnEnd } from "@/services/sseTrace";
import { notifyTurnQueued } from "@/services/turns/queuedNotify";
import {
  completeTurnPhase,
  getRuntime,
  getTurnPhase,
  isTerminalPhase,
  lastAssistantProjectionId,
  useConversationStore,
} from "@/stores/conversation";
import {
  execRuntime,
  hasUnsettledRuns,
  useExecutionStore,
} from "@/stores/execution";
import { clearInteractionPrompts } from "@/stores/interactionPrompts";
import type {
  ContentDeltaPayload,
  ContentResetPayload,
  ErrorPayload,
  MessageEndPayload,
  MessageStartPayload,
  ReasoningDeltaPayload,
  SSEEvent,
  ToolProgressPayload,
  TurnQueuedPayload,
  TurnWarningPayload,
} from "@/types/events";
import { resetCaptainContext } from "../captainContext";
import {
  discardAllPendingChunks,
  discardPendingContent,
  ensureStreamingAssistant,
  flushPendingContent,
  queueContentDelta,
  queueReasoningDelta,
} from "../contentBuffer";
import { flushPendingFrames } from "../execFrameBuffer";
import { clearGraphAppendRedirect } from "../helpers";
import type { DispatchContext } from "../types";

function finalizeTurnTrace(conversationId: string): void {
  const msgs = getRuntime(conversationId).messages;
  const lastA = [...msgs].reverse().find((m) => m.role === "assistant");
  traceTurnEnd(conversationId, lastA?.process);
}

export function handleMessageStreamEvent(
  event: SSEEvent,
  ctx: DispatchContext,
): boolean {
  const { conversationId } = ctx;

  switch (event.type) {
    case "turn_queued": {
      // EPHEMERAL（不进 journal / conformance ProjectedTurn）——与 fold 穷尽 no-op
      // 对齐；live 仅呈现既有「已排队」toast，随后同连接自然续流。
      const p = event.payload as TurnQueuedPayload;
      notifyTurnQueued(p.position ?? 1, p.queue_depth ?? 1);
      return true;
    }
    case "turn_warning": {
      const payload = event.payload as TurnWarningPayload;
      useConversationStore
        .getState()
        .recordTurnWarning(payload.message, conversationId);
      return true;
    }
    case "message_start": {
      const payload = event.payload as MessageStartPayload;
      // Resume = same-turn continuation: if an assistant already matches the
      // server message_id, reuse it (idempotent). Never delete+create.
      const store = useConversationStore.getState();
      // 跨回合回放 / 同连接下一回合：上一回合 message_end 已进 terminal，须先拨回
      // streaming，否则 ensureStreamingAssistant 与后续生长帧会被门禁丢掉。
      if (isTerminalPhase(getTurnPhase(conversationId))) {
        store.setTurnPhase("streaming", conversationId);
      }
      const existing = payload.message_id
        ? getRuntime(conversationId).messages.find(
            (m) =>
              m.role === "assistant" &&
              (m.id === payload.message_id ||
                m.serverMessageId === payload.message_id),
          )
        : undefined;
      if (existing) {
        if (!existing.isStreaming) {
          store.resumePausedAssistant(payload.message_id, conversationId);
        } else {
          store.setGenerating(true, conversationId);
        }
      } else {
        ensureStreamingAssistant(conversationId);
        // 换回合（陌生 message_id）：复用的尾部占位气泡若带着上一段生命的残留
        // 正文/思考/过程（如被上一回合回放污染的乐观占位），先清干净再开流——
        // 对齐 conformanceFold 的 message_start 语义（message_id 变化 ⇒ 空正文），
        // 消除 live/fold 漂移。未写出的 rAF 缓冲同属上一段生命，一并丢弃。
        discardAllPendingChunks(conversationId);
        store.resetAssistantForNewTurn(payload.message_id, conversationId);
        store.setGenerating(true, conversationId);
      }
      store.stampPendingTurnWarning(conversationId);
      if (payload.trace_id)
        store.setTraceIdOnLastMessage(payload.trace_id, conversationId);
      // Stamp server turn id (and one-time align execution client→server).
      store.setServerMessageIdOnLastMessage(payload.message_id, conversationId);
      // Turn (re)start — clear the captain context accumulator so a reconnect replay
      // (which re-sends message_start first) rebuilds it idempotently (上下文传递可视化 通道①+⑤).
      resetCaptainContext(conversationId);
      return true;
    }
    case "content_delta": {
      ensureStreamingAssistant(conversationId);
      queueContentDelta(
        conversationId,
        (event.payload as ContentDeltaPayload).delta,
      );
      return true;
    }
    case "content_reset": {
      discardPendingContent(conversationId);
      useConversationStore
        .getState()
        .resetStreamingContent(
          (event.payload as ContentResetPayload).reason,
          conversationId,
        );
      return true;
    }
    case "reasoning_delta": {
      ensureStreamingAssistant(conversationId);
      // rAF 合批思考流 (流式性能): 与正文共用一条 rAF、同点 flush，避免逐 token 写 store。
      queueReasoningDelta(
        conversationId,
        (event.payload as ReasoningDeltaPayload).delta,
      );
      return true;
    }
    case "tool_progress": {
      ensureStreamingAssistant(conversationId);
      const p = event.payload as ToolProgressPayload;
      useConversationStore
        .getState()
        .setComposingTool(
          { toolName: p.tool_name, chars: p.chars },
          conversationId,
        );
      return true;
    }
    case "message_end": {
      flushPendingContent(conversationId);
      // Land any rAF-buffered worker frames before the turn finalizes so the graph's
      // last deltas aren't dropped on a fast end (流式性能合批的收尾兜底).
      flushPendingFrames(conversationId);
      const payload = event.payload as MessageEndPayload;
      const conv = useConversationStore.getState();
      if (payload.cost) {
        conv.attachCostToLastMessage(payload.cost, conversationId);
      }
      const usage = payload.usage;
      conv.attachTurnMetaToLastMessage(
        {
          usage: usage
            ? {
                input: usage.input_tokens,
                output: usage.output_tokens,
                reasoning: usage.reasoning_tokens,
                cache_hit: usage.cache_hit_tokens,
                cache_miss: usage.cache_miss_tokens,
              }
            : undefined,
          rounds: payload.rounds,
          durationMs:
            typeof payload.duration_ms === "number"
              ? payload.duration_ms
              : undefined,
          finishReason: payload.finish_reason,
          collab: payload.collab,
        },
        conversationId,
      );
      conv.finalizeLastMessage(conversationId);
      clearInteractionPrompts(conversationId);
      // 挂起即收口 (②): a turn can END at a durable checkpoint — message_end carries
      // finish_reason=paused. The turn is NOT done: its frame was persisted and its
      // in-process resolve Future was never parked, so keep the graph paused (not
      // "completed") and let the now-dormant inline checkpoint card hand off to the
      // (single) durable resume card, surfaced from the *_required payload already on the
      // bubble (no /recovery round-trip → reproduces offline in #/preview).
      const paused = payload.finish_reason === "paused";
      // 只收口【本回合】助手槽；跨回合同图追加时生长帧在宿主卡，不得被追加回合
      // message_end 误标 completed（图完成态由 execution 内 run 终态 reconcile）。
      const mid = lastAssistantProjectionId(
        getRuntime(conversationId).messages,
      );
      if (mid) {
        const rt = execRuntime(useExecutionStore.getState(), mid);
        if (rt.plan && rt.status !== "failed") {
          // 后台托管继续跑 (coordination.turn_detached): CEO 回合结束时图内仍有
          // running/pending **worker** —— 不塌成 completed（否则状态条冻在残缺计数、
          // finalizeFold 把未跑节点标「未执行」，而其余节点还显示「执行中」）。保持
          // running，交由 recordFrame(s) 的 run 终态 reconcile 在最后一个托管 worker
          // 终态帧落时收口（经重连回放 / 跨回合追加送达）。paused 收口与「工人已终态」
          // 两条路径不变。Captain 假 pending（pre-plan run_started 被丢）不参与 hold，
          // 否则 end_turn 后会永久钉在「正在生成汇总」。
          // cancelled/interrupted：后端终态权威，立刻定格（finalizeFold 冻残留 running）。
          const cancelled =
            payload.finish_reason === "cancelled" ||
            payload.finish_reason === "interrupted";
          if (paused) {
            useExecutionStore.getState().setStatus("paused", mid);
          } else if (cancelled) {
            useExecutionStore.getState().setStatus("cancelled", mid);
          } else if (!hasUnsettledRuns(rt)) {
            useExecutionStore.getState().setStatus("completed", mid);
          }
        }
      }
      conv.releaseBackgroundSlice(conversationId);
      finalizeTurnTrace(conversationId);
      clearGraphAppendRedirect(conversationId);
      if (paused) surfaceResumeFromLiveTurn(conversationId, ctx.source);
      // 正常完成 / 停止确认：推进生命周期。stopping → stopped；其余 → completed。
      // 超时已进 terminal 则不覆盖（避免 stopped 被迟到 message_end 改成 completed）。
      if (!isTerminalPhase(getTurnPhase(conversationId))) {
        completeTurnPhase(
          conversationId,
          getTurnPhase(conversationId) === "stopping" ? "stopped" : "completed",
        );
      }
      return true;
    }
    case "error": {
      flushPendingContent(conversationId);
      flushPendingFrames(conversationId);
      ensureStreamingAssistant(conversationId);
      const store = useConversationStore.getState();
      const payload = event.payload as ErrorPayload;
      store.attachErrorToLastMessage(
        {
          code: payload.code,
          message: payload.message,
          context: payload.context,
        },
        conversationId,
      );
      store.finalizeLastMessage(conversationId);
      clearInteractionPrompts(conversationId);
      const mid = lastAssistantProjectionId(
        getRuntime(conversationId).messages,
      );
      if (mid && execRuntime(useExecutionStore.getState(), mid).plan) {
        useExecutionStore.getState().setStatus("failed", mid);
      }
      store.releaseBackgroundSlice(conversationId);
      finalizeTurnTrace(conversationId);
      clearGraphAppendRedirect(conversationId);
      if (!isTerminalPhase(getTurnPhase(conversationId))) {
        completeTurnPhase(
          conversationId,
          getTurnPhase(conversationId) === "stopping" ? "stopped" : "failed",
        );
      }
      return true;
    }
    default:
      return false;
  }
}
