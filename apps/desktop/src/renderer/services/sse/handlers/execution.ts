import { EXECUTION_RECORD_TOOLS } from "@/lib/executionRecords";
import { useConversationStore } from "@/stores/conversation";
import {
  execRuntime,
  frameFromEvent,
  planFromRunPlan,
  useExecutionStore,
} from "@/stores/execution";
import {
  INTERACTION_BY_KIND,
  applyInteractionWireEvent,
} from "@/stores/interactions";
import { useToolOutputLiveStore } from "@/stores/toolOutputLive";
import type {
  CoordinationWaitPayload,
  DebateResultPayload,
  DebateRoundPayload,
  DebateRoundStartedPayload,
  DeliveryStatusPayload,
  EscalationRequiredPayload,
  ExecutionDetachedPayload,
  GraphAppendPayload,
  RunContextPayload,
  RunEscalationPayload,
  RunPlanPayload,
  RunStartedPayload,
  SSEEvent,
  TeamSynthesisPreviewPayload,
  ToolUseEndPayload,
  ToolUseProgressPayload,
  ToolUseStartPayload,
} from "@/types/events";
import {
  growCaptainContext,
  isCaptainRun,
  setCaptainRunId,
} from "../captainContext";
import { flushPendingContent } from "../contentBuffer";
import { flushPendingFrames, queueFrame } from "../execFrameBuffer";
import {
  ceoMessageId,
  execMessageId,
  noteGraphAppendRedirect,
  routeHintFromPayload,
} from "../helpers";
import { refreshAfterExecutionCompleted } from "../refreshAfterExecutionCompleted";
import type { DispatchContext } from "../types";

/** Stamp an escalation process marker (required or raised) onto the CEO lane. */
function stampEscalationTimelineMarker(
  escalationId: string,
  conversationId: string,
): void {
  const timeline = INTERACTION_BY_KIND.escalation.timeline;
  if (!timeline || !escalationId) return;
  // Flush rAF-buffered CEO prose first so the marker lands AFTER any same-round
  // lead-in text (mirrors the synchronous conformance fold's ordering).
  flushPendingContent(conversationId);
  useConversationStore
    .getState()
    .stampTimelineMarker(timeline, escalationId, conversationId);
}

/** A structural (low-frequency) frame: flush any rAF-buffered hot frames FIRST so global
 * frame order is preserved, then append this one immediately. */
function recordFrameNow(event: SSEEvent, conversationId: string): void {
  flushPendingFrames(conversationId);
  const mid = execMessageId(
    conversationId,
    routeHintFromPayload(event.payload),
  );
  const frame = frameFromEvent(event);
  if (mid && frame) useExecutionStore.getState().recordFrame(frame, mid);
}

/** A high-frequency accumulate-only frame (run_*_delta / tool_progress / output_reset):
 * coalesce into the next animation frame ({@link queueFrame}) instead of a per-token store
 * write — the 白屏卡死 fix (逐 token → ≤60Hz). */
function queueFrameEvent(event: SSEEvent, conversationId: string): void {
  const frame = frameFromEvent(event);
  if (frame) queueFrame(conversationId, frame);
}

export function handleExecutionEvent(
  event: SSEEvent,
  ctx: DispatchContext,
): boolean {
  const { conversationId } = ctx;

  switch (event.type) {
    case "graph_append": {
      // 跨回合同图追加锚点——落在【追加回合】process；生长帧走 host 槽。
      const p = event.payload as GraphAppendPayload;
      flushPendingContent(conversationId);
      noteGraphAppendRedirect(conversationId, p.host_message_id);
      useConversationStore.getState().stampGraphAppend(p, conversationId);
      return true;
    }
    case "run_plan": {
      const payload = event.payload as RunPlanPayload;
      if (payload.host_message_id) {
        noteGraphAppendRedirect(conversationId, payload.host_message_id);
      }
      const mid = execMessageId(conversationId, {
        host_message_id: payload.host_message_id,
        execution_id: payload.execution_id,
      });
      if (!mid) return true;
      useExecutionStore.getState().ingestPlan(planFromRunPlan(payload), mid);
      // 追加回合：不在最新助手气泡插 team / 盖 executionId（宿主卡已有）。
      if (payload.host_message_id) return true;
      if (
        payload.plan_type === "multi_agent" ||
        payload.plan_type === "debate"
      ) {
        // Flush any rAF-buffered content FIRST so it lands as content step(s) BEFORE the
        // `team` marker — the collaboration graph slots after the CEO's intro line, not
        // above it (协作图时间线落点; matches the conformance golden's [content, team] order).
        flushPendingContent(conversationId);
        useConversationStore
          .getState()
          .setLastAssistantExecutionId(payload.execution_id, conversationId);
      }
      return true;
    }
    case "run_started": {
      const p = event.payload as RunStartedPayload;
      if (p.kind === "captain") setCaptainRunId(conversationId, p.run_id);
      recordFrameNow(event, conversationId);
      return true;
    }
    case "run_context": {
      const p = event.payload as RunContextPayload;
      if (isCaptainRun(conversationId, p.run_id)) {
        const grown = growCaptainContext(conversationId, p.blocks);
        useConversationStore
          .getState()
          .setCaptainContext(grown, conversationId);
        return true;
      }
      recordFrameNow(event, conversationId);
      return true;
    }
    // 高频纯累积帧 (流式性能，白屏卡死修复): rAF 合批，避免逐 token 全图重折叠 + 全消费者重
    // 渲染 (整条流 O(n²))。run_output_reset (交付前核验回炉 finish_guard 的 worker 对偶,
    // content_reset 之于 CEO 气泡: 清 worker 已流式累积的草稿产出、重写版从干净态重累积) 也走
    // 同一有序缓冲，故与它清理的 delta 天然保序。Folds via the same frame path; transport-only.
    case "run_output_delta":
    case "run_output_reset":
    case "run_reasoning_delta":
    case "run_tool_progress": {
      queueFrameEvent(event, conversationId);
      return true;
    }
    // 结构性帧 (低频): recordFrameNow 先 flush 高频缓冲以保帧顺序，再立即落。
    case "run_completed":
    case "run_failed":
    case "run_cancelled":
    case "run_skipped":
    case "run_progress":
    // 调度埋点量化 (深层诊断指标): the WaveScheduler snapshot folds onto Execution.batches via
    // the same frame path (journaled → replays on reload); shown only in 诊断模式 (run detail).
    case "batch_metrics":
    // 「计划已调整」轻痕迹 (设计 §7.2): a NON-interrupting trace — the CEO re-bound / re-steered
    // paused nodes via replan. Folds onto the runs' `revised` via the same frame path (no
    // conversation-store gate); journaled, so it replays on reload.
    case "plan_revised":
    case "run_escalation":
    // Worker 内部路由 Phase 1：Escalation Gate — 诊断帧；Phase 1 无独立 UI，
    // 仍走 frame 路径以便 journal 重放时不丢事件。
    case "run_escalation_gate":
    // 阻塞式求决策: a worker SUSPENDED on a blocking escalate (escalation_required) then settled
    // (escalation_resolved). Both fold onto the run's escalations via the same frame path
    // (projectExecution appends `pending` / flips `resolved`|`assumed`|`timed_out`), driving the bubble's
    // EscalationCard + the node badge. UNLIKE the gates (approval / plan_review) they do NOT pause
    // the turn — siblings keep running — so there is no conversation-store card, just the journaled
    // frame; both are journaled, so the exchange replays inline on reload.
    // 统一时间线二期: escalation_required / run_escalation 另 stamp CEO 时间线标记（sseVia=execution，
    // 不经 interaction 盖章路径）。
    case "escalation_required":
    case "escalation_resolved": {
      applyInteractionWireEvent(
        event.type,
        (event.payload ?? {}) as Record<string, unknown>,
        conversationId,
        execMessageId(conversationId, routeHintFromPayload(event.payload)) ??
          "",
      );
      if (event.type === "escalation_required") {
        const eid = (event.payload as EscalationRequiredPayload)?.escalation_id;
        if (typeof eid === "string" && eid) {
          stampEscalationTimelineMarker(eid, conversationId);
        }
      } else if (event.type === "run_escalation") {
        const eid = (event.payload as RunEscalationPayload)?.escalation_id;
        if (typeof eid === "string" && eid) {
          stampEscalationTimelineMarker(eid, conversationId);
        }
      }
      recordFrameNow(event, conversationId);
      return true;
    }
    // 团队便签墙 (§2.2 通): a worker broadcast a one-line decision / heads-up to its
    // concurrent siblings. Turn-level (folds onto Execution.teamNotes via the same frame
    // path, not onto a node); journaled, so it replays on reload. Fire-and-forget — it never
    // pauses the turn (no conversation-store card), just the journaled frame.
    case "team_note_posted": {
      recordFrameNow(event, conversationId);
      return true;
    }
    // CEO 协调模式：多 worker 团队进展摘要。P2 DURABLE——入 journal；live 另 stamp 到
    // execution runtime（同 key 保最新），hydrateFromJournal 取最后一条重建，供 StatusStrip
    // 「团队进展」预览行。
    case "team_synthesis_preview": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        useExecutionStore
          .getState()
          .setTeamSynthesisPreview(
            event.payload as TeamSynthesisPreviewPayload,
            mid,
          );
      }
      return true;
    }
    // CEO 协调等待：captain 空等团队事件。EPHEMERAL——仅 live；waiting=false 清除。
    case "coordination_wait": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        useExecutionStore
          .getState()
          .setCoordinationWait(event.payload as CoordinationWaitPayload, mid);
      }
      return true;
    }
    // 执行转后台：附着回合已收口，团队继续跑。EPHEMERAL live stamp → StatusStrip
    // 静态「团队后台运行中」；conformanceFold 保持 no-op。
    case "execution_detached": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        useExecutionStore
          .getState()
          .setExecutionDetached(event.payload as ExecutionDetachedPayload, mid);
      }
      return true;
    }
    // 后台执行终态：清后台 chrome、标完成、刷新对话以拉入 harvest 终稿。
    case "execution_completed": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        const exec = useExecutionStore.getState();
        exec.setExecutionDetached(null, mid);
        const rt = execRuntime(exec, mid);
        if (rt.plan && rt.status === "running") {
          exec.setStatus("completed", mid);
        }
      }
      refreshAfterExecutionCompleted(conversationId);
      return true;
    }
    // 交付状态（能力闸门与交付诚实性）：delegate 批次收尾的结构化交付对账。DURABLE——
    // 入 journal；live 另 stamp 到 execution runtime（同 execution_id 保最新），
    // hydrateFromJournal 取最后一条重建，驱动答复下方的交付状态卡。
    case "delivery_status": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        useExecutionStore
          .getState()
          .setDeliveryStatus(event.payload as DeliveryStatusPayload, mid);
      }
      return true;
    }
    case "user_interjection": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        const p = event.payload as {
          interjection_id?: string;
          execution_id?: string;
          content?: string;
          status?: string;
          note?: string | null;
          attachments?: Array<{
            name?: string;
            workspace_path?: string;
            binary?: boolean;
          }>;
        };
        const iid = (p.interjection_id || "").trim();
        if (iid) {
          const attachments = (p.attachments ?? [])
            .filter(
              (
                a,
              ): a is {
                name: string;
                workspace_path?: string;
                binary?: boolean;
              } => typeof a.name === "string" && Boolean(a.name.trim()),
            )
            .map((a) => ({
              name: a.name.trim(),
              workspacePath:
                typeof a.workspace_path === "string" && a.workspace_path.trim()
                  ? a.workspace_path
                  : undefined,
              binary: Boolean(a.binary),
            }));
          useExecutionStore.getState().upsertUserInterjection(
            {
              interjectionId: iid,
              executionId: p.execution_id || "",
              content: p.content || "",
              status: p.status || "delivered",
              note: typeof p.note === "string" ? p.note : null,
              ...(attachments.length > 0 ? { attachments } : {}),
            },
            mid,
          );
        }
      }
      return true;
    }
    case "tool_use_start": {
      // Worker-scoped tools ride the host graph under divert; CEO orchestration stays
      // on the appending turn (anchor / tool card).
      const startPayload = event.payload as ToolUseStartPayload;
      if (startPayload.run_id) {
        recordFrameNow(event, conversationId);
      } else {
        flushPendingFrames(conversationId);
        const mid = ceoMessageId(conversationId);
        const frame = frameFromEvent(event);
        if (mid && frame) useExecutionStore.getState().recordFrame(frame, mid);
      }
      flushPendingContent(conversationId);
      if (EXECUTION_RECORD_TOOLS.has(startPayload.tool_name)) {
        useToolOutputLiveStore.getState().seed({
          toolCallId: startPayload.tool_call_id,
          toolName: startPayload.tool_name,
          conversationId,
        });
      }
      useConversationStore
        .getState()
        .addProcessTool(startPayload, conversationId);
      return true;
    }
    case "tool_use_end": {
      const endPayload = event.payload as ToolUseEndPayload;
      if (endPayload.run_id) {
        recordFrameNow(event, conversationId);
        const mid = execMessageId(
          conversationId,
          routeHintFromPayload(endPayload),
        );
        if (mid)
          useExecutionStore
            .getState()
            .clearWorkerToolPhase(endPayload.run_id, mid);
      } else {
        flushPendingFrames(conversationId);
        const mid = ceoMessageId(conversationId);
        const frame = frameFromEvent(event);
        if (mid && frame) useExecutionStore.getState().recordFrame(frame, mid);
      }
      flushPendingContent(conversationId);
      // 结束态权威输出在 display；保留 live buffer 至会话清理，供竞态帧回落。
      if (EXECUTION_RECORD_TOOLS.has(endPayload.tool_name)) {
        useToolOutputLiveStore.getState().markEnded(endPayload.tool_call_id);
      }
      useConversationStore
        .getState()
        .endProcessTool(endPayload, conversationId);
      return true;
    }
    // 工具执行阶段进度 (联网搜索前端展示优化): a running tool reported a coarse EXECUTION phase
    // (web_search → querying / queued / fallback). Transport-only liveliness — NOT journaled, so
    // no frame is recorded (a reloaded turn's tools are already resolved); it only stamps the live
    // running tool step's phase for the waiting UI.
    // M2：code_execute / test_run 的 phase=output + {stream,chunk} 另写入 live-only buffer。
    case "tool_use_progress": {
      const progressPayload = event.payload as ToolUseProgressPayload;
      if (progressPayload.phase === "output") {
        useToolOutputLiveStore
          .getState()
          .appendProgress(progressPayload, conversationId);
      }
      if (progressPayload.run_id) {
        const mid = execMessageId(
          conversationId,
          routeHintFromPayload(progressPayload),
        );
        if (mid)
          useExecutionStore.getState().setWorkerToolPhase(progressPayload, mid);
      } else {
        useConversationStore
          .getState()
          .setProcessToolPhase(progressPayload, conversationId);
      }
      return true;
    }
    case "debate_result": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid)
        useExecutionStore
          .getState()
          .recordDebateResult(event.payload as DebateResultPayload, mid);
      return true;
    }
    case "debate_round_started": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        const p = event.payload as DebateRoundStartedPayload;
        const store = useExecutionStore.getState();
        store.recordDebateRound(
          {
            round_no: p.round_no,
            focus: p.focus,
            summary: "",
            verdict: null,
            sides: [],
            clashes: [],
            cross_exam: [],
            findings: [],
            thread_turns: [],
          },
          mid,
        );
        if (p.cross_exam_enabled === true) {
          store.recordCrossExamEnabled(true, mid);
        }
        const rawOpening = (p.opening ?? "").trim();
        if (rawOpening) {
          store.recordDebateOpening(rawOpening, mid);
        }
      }
      return true;
    }
    case "debate_round": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        const p = event.payload as DebateRoundPayload;
        const store = useExecutionStore.getState();
        store.recordDebateRound(
          {
            round_no: p.round_no,
            focus: p.focus,
            summary: p.summary,
            verdict: p.verdict,
            sides: p.sides,
            clashes: p.clashes,
            cross_exam: p.cross_exam ?? [],
            findings: p.findings ?? [],
            thread_turns: p.thread_turns ?? [],
          },
          mid,
        );
        if (p.evidence_ledger_delta?.length) {
          store.recordEvidenceLedgerDelta(p.evidence_ledger_delta, mid);
        }
      }
      return true;
    }
    case "debate_pretrial_started":
    case "debate_pretrial_orders":
    case "debate_pretrial_progress":
    case "debate_pretrial_completed": {
      const mid = execMessageId(
        conversationId,
        routeHintFromPayload(event.payload),
      );
      if (mid) {
        useExecutionStore
          .getState()
          .recordDebatePretrial(event.type, event.payload, mid);
      }
      return true;
    }
    default:
      return false;
  }
}
