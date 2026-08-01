import { DebateView, LiveDebateNarrative } from "@/components/DebateView";
import { Markdown } from "@/components/Markdown";
import { NonBlockingAskCard } from "@/components/NonBlockingAskCard";
import {
  EscalationAnswer,
  TeamView,
  escalationDetail,
} from "@/components/TeamView";
import {
  CONTEXT_CHANNEL_LABEL,
  toolDetail,
  toolLabel,
} from "@/components/assistantLabels";
import { isFileReadCeilingGuidance } from "@/lib/fileReadCeiling";
import {
  type MessageCopyMode,
  copyText,
  formatMessageExport,
} from "@/lib/messageExport";
import {
  type SupportDiagnosticIds,
  formatSupportDiagnosticText,
} from "@/lib/supportDiagnostics";
import { isVerifyBudgetExceeded } from "@/lib/verifyBudget";
import type {
  EscalationSlot,
  HotDecisionTrace,
  NonBlockingAsk,
  RunToolCall,
  StageCardTrace,
} from "@/protocol/fold";
import { actAuthorizedByLabel } from "@/protocol/fold";
// Rich assistant rendering shared by live turns and history replay (前端技术与架构 §七 ·
// 富渲染 + 多 Agent 团队视图). One {@link AssistantContent} consumes the same fields whether
// they come from the live fold (ProjectedTurn) or a persisted message (MessageDetail).
//
// 统一团队时间线: every turn renders its `process` timeline (正文 / 思考 / 工具, interleaved);
// for history it is restored from MessageDetail.runs.process. A multi-agent turn additionally
// carries a `team` positional marker in that timeline — the collaboration graph slots inline
// at the marker (协作图时间线落点), re-folded from MessageDetail.runs.events for history.
// The checkpoint·ask·plan_review markers are anchors for desktop's inline cards; mobile owns
// those interactions via its PauseCard, so they no-op in the timeline.
//
// Citations render as a source list under the message either way.
import type {
  Citation,
  ContextBlockWire,
  DebateNarrativeRound,
  DebateResultPayload,
  EvidenceLedgerEntry,
  ProcessStep,
  ToolPhase,
} from "@agentcore/contract-types";
import type {
  ProjectedAct,
  ProjectedAgent,
  ProjectedRun,
  ProjectedTeamNote,
  TurnStatus,
} from "@agentcore/protocol-conformance";
import { useEffect, useState } from "react";

type ToolStepData = Extract<ProcessStep, { kind: "tool" }>;

/** 跨回合同图追加锚点文案（批 A4）：开辩论幕与同幕补派区分；手机列表语气，非桌面 ↑ 跳转条。 */
export function graphAppendAnchorLabel(
  addedCount: number,
  actKind?: string | null,
  authorizedBy?: string | null,
): string {
  const n = Math.max(0, addedCount | 0);
  const base =
    actKind === "debate"
      ? `已开辩论幕 · 追加 ${n} 名成员`
      : `已往上方协作图追加 ${n} 名成员`;
  const auth = actAuthorizedByLabel(authorizedBy);
  return auth ? `${base} · ${auth}` : base;
}

export interface TeamProjection {
  agents: ProjectedAgent[];
  runs: ProjectedRun[];
  progress: { completed: number; total: number };
  /** 幕序列（批 A4）：透传给 {@link TeamView} 做多幕列表分组。 */
  acts?: ProjectedAct[];
  /** 团队便签墙 (§2.2 通): notes workers broadcast to their concurrent siblings this turn
   *  (`team_note_posted`), in post order — rendered by {@link TeamView}. Optional so the promo
   *  still (which builds team from a truncated vector) and legacy callers keep compiling. */
  teamNotes?: ProjectedTeamNote[];
  /** 交付状态（`delivery_status`，能力闸门与交付诚实性）：delegate 收尾的结构化交付对账，
   *  由 {@link TeamView} 在 partial / blocked 时渲染。Optional（旧调用方 / promo 兼容）。 */
  deliveryStatus?:
    | import("@agentcore/contract-types").DeliveryStatusPayload
    | null;
  /** Turn lifecycle from ProjectedTurn — drives team-notes default expand/collapse. */
  status?: TurnStatus | null;
  /** 阻塞式求决策 (②): forwarded straight to {@link TeamView} via the `{...team}` spread so a
   *  worker's pending escalation can render as an actionable answer card. All optional — a
   *  read-only / history team simply omits them. */
  conversationId?: string | null;
  /** runId → pending escalation id from ProjectedTurn.interactions (P3). */
  pendingEscalations?: Map<string, string>;
  /** Live turn → the pending escalation is answerable over the open stream. */
  escalationsInteractive?: boolean;
  /** 队员工具明细 (RunDetail · 工具调用): runId → the worker's tool calls, from the transport-only
   *  sibling {@link import("@/protocol/fold").extractRunToolCalls} (the fold drops run-scoped tool
   *  IO, so the run-detail panel reads it from here). Absent → the panel shows no tool section. */
  runToolCalls?: Map<string, RunToolCall[]>;
  /** Worker `tool_use_progress` (run_id): runId → live EXECUTION phase (transport-only sibling
   *  {@link import("@/protocol/fold").extractWorkerToolPhases}). */
  workerToolPhases?: Map<string, { phase: string; toolName: string }>;
  /** 场级证据台账（`extractEvidenceLedger`）：辩论徽章 `#eN` 解析。 */
  evidenceLedger?: EvidenceLedgerEntry[];
}

export function AssistantContent({
  process,
  content,
  reasoning,
  citations,
  evidenceLedger,
  captainContext,
  team,
  debate,
  debateRounds,
  debatePretrial,
  asks,
  escalationSlots,
  hotTraces,
  stageCardTraces,
  toolPhases,
  graphAppendActKinds,
  graphAppendAuthorizedBy,
  onFill,
  supportIds,
}: {
  process?: ProcessStep[];
  content: string;
  reasoning?: string;
  citations?: Citation[];
  /** 回合调研台账（`#rN`）：live=`ProjectedTurn.evidenceLedger`；history=`MessageDetail.evidenceLedger`。
   *  与 `team.evidenceLedger`（辩论场级 `#eN`）是两通道，勿混用。 */
  evidenceLedger?: EvidenceLedgerEntry[];
  /** 收到的上下文 · CEO 侧 (上下文传递可视化 通道①): what the CEO captain actually read this
   *  turn (系统提示 / 对话历史 / 原始请求), rendered turn-level on its bubble — present even on a
   *  pure-chat turn (no team). */
  captainContext?: ContextBlockWire[];
  team?: TeamProjection;
  debate?: DebateResultPayload | null;
  /** 辩论进行中的逐轮叙事 (fold 的 `debateRounds`)：`debate` 收场产物未到时实时叠出主持人逐
   *  轮焦点 / 小结 / 裁判；收场后让位给 {@link DebateView} 的全量双产物。 */
  debateRounds?: DebateNarrativeRound[];
  /** 庭前取证（fold 的 `debatePretrial`）；开赛后首轮前 / 收场复盘。 */
  debatePretrial?:
    | import("@agentcore/protocol-conformance").DebatePretrialProjection
    | null;
  /** 非阻塞提问 (ask_user blocking=false): transport-only card content keyed by ask_id,
   *  read off raw events via {@link extractAsks} (NOT the ProjectedTurn). The timeline's
   *  `ask` marker resolves to its card here; empty/absent → the marker no-ops. */
  asks?: NonBlockingAsk[];
  /** 升级时间线槽 (统一时间线二期): escalation_id → card body (extractEscalationSlots). */
  escalationSlots?: Map<string, EscalationSlot>;
  /** 热审批/委派授权痕迹 (D3): id → resolved 轻行内容 (extractHotDecisionTraces). */
  hotTraces?: Map<string, HotDecisionTrace>;
  /** 阶段推进卡时间线痕迹：id → resolved/orphaned 轻行 (extractStageCardTraces)。 */
  stageCardTraces?: Map<string, StageCardTrace>;
  /** 工具执行阶段进度 (联网搜索前端展示优化): tool_call_id → latest coarse phase for a still-running
   *  tool, from the transport-only live sibling {@link extractToolPhases}. Live turns only; absent
   *  on history replay (the events are never journaled) → tool rows show plain status. */
  toolPhases?: Map<string, ToolPhase>;
  /** graph_append 开幕 kind（`extractGraphAppendActKinds`）：开辩论幕锚点文案。 */
  graphAppendActKinds?: Map<string, string>;
  /** graph_append 授权来源（`extractGraphAppendAuthorizedBy`）：锚点副文案。 */
  graphAppendAuthorizedBy?: Map<string, string>;
  /** Tap an ask/chip → fill the composer (回填输入框, review before send). Absent → chips
   *  render but no-op (e.g. a read-only context with no composer). */
  onFill?: (text: string) => void;
  /** 复制排查包 ids（报障 / Cursor 日志查询）；有任一 id 即在复制行显示入口. */
  supportIds?: SupportDiagnosticIds;
}) {
  const hasTeam = !!team && team.runs.length > 0;
  const turnLedger = evidenceLedger;
  return (
    <>
      {debate ? (
        <DebateView debate={debate} pretrial={debatePretrial} onFill={onFill} />
      ) : debateRounds && debateRounds.length > 0 ? (
        <LiveDebateNarrative rounds={debateRounds} pretrial={debatePretrial} />
      ) : debatePretrial ? (
        <LiveDebateNarrative rounds={[]} pretrial={debatePretrial} />
      ) : null}
      {process && process.length > 0 ? (
        // 统一团队时间线: the team graph rides its inline `team` marker; escalation /
        // approval / delegation markers render at their own slots (二期).
        <ProcessTimeline
          steps={process}
          citations={citations}
          evidenceLedger={turnLedger}
          team={hasTeam ? team : undefined}
          asks={asks}
          escalationSlots={escalationSlots}
          hotTraces={hotTraces}
          stageCardTraces={stageCardTraces}
          toolPhases={toolPhases}
          graphAppendActKinds={graphAppendActKinds}
          graphAppendAuthorizedBy={graphAppendAuthorizedBy}
          onFill={onFill}
        />
      ) : (
        <>
          {hasTeam ? <TeamView {...team} /> : null}
          {reasoning ? <Reasoning text={reasoning} /> : null}
          {content ? (
            <Markdown
              content={content}
              citations={citations}
              evidenceLedger={turnLedger}
            />
          ) : null}
        </>
      )}
      {captainContext && captainContext.length > 0 ? (
        <ReceivedContext blocks={captainContext} />
      ) : null}
      {citations && citations.length > 0 ? (
        <Citations items={citations} />
      ) : null}
      <MessageCopyActions
        content={content}
        process={process}
        supportIds={supportIds}
      />
    </>
  );
}

/** 复制出口：仅交付 / 含过程 + 恒可用的「复制排查包」（对齐桌面报障出口）. */
function MessageCopyActions({
  content,
  process,
  supportIds,
}: {
  content: string;
  process?: ProcessStep[];
  supportIds?: SupportDiagnosticIds;
}) {
  const [copied, setCopied] = useState<MessageCopyMode | "support" | null>(
    null,
  );
  const supportText = supportIds ? formatSupportDiagnosticText(supportIds) : "";
  const hasContent = !!content.trim() || (process && process.length > 0);
  if (!hasContent && !supportText) return null;
  const hasProcess = (process?.length ?? 0) > 0;

  const onCopy = async (mode: MessageCopyMode) => {
    const text = formatMessageExport(content, process, mode);
    if (await copyText(text)) {
      setCopied(mode);
      window.setTimeout(() => setCopied(null), 1500);
    }
  };

  const onCopySupport = async () => {
    if (!supportText) return;
    if (await copyText(supportText)) {
      setCopied("support");
      window.setTimeout(() => setCopied(null), 1500);
    }
  };

  return (
    <div className="msg-copy">
      {hasContent && (
        <button
          type="button"
          className="msg-copy-btn"
          onClick={() => void onCopy("deliverable")}
        >
          {copied === "deliverable" ? "已复制" : "复制交付"}
        </button>
      )}
      {hasContent && hasProcess && (
        <button
          type="button"
          className="msg-copy-btn"
          onClick={() => void onCopy("with_process")}
        >
          {copied === "with_process" ? "已复制" : "含过程"}
        </button>
      )}
      {supportText && (
        <button
          type="button"
          className="msg-copy-btn"
          onClick={() => void onCopySupport()}
        >
          {copied === "support" ? "已复制" : "复制排查包"}
        </button>
      )}
    </div>
  );
}

/** Inline error-row「复制排查包」(empty failure bubbles have no MessageCopyActions). */
export function SupportDiagnosticCopyButton({
  ids,
}: {
  ids: SupportDiagnosticIds;
}) {
  const [copied, setCopied] = useState(false);
  const text = formatSupportDiagnosticText(ids);
  if (!text) return null;
  return (
    <button
      type="button"
      className="msg-copy-btn"
      onClick={() => {
        void copyText(text).then((ok) => {
          if (!ok) return;
          setCopied(true);
          window.setTimeout(() => setCopied(false), 1500);
        });
      }}
    >
      {copied ? "已复制" : "复制排查包"}
    </button>
  );
}

/** 收到的上下文 · CEO 侧 (上下文传递可视化 通道①): the structured context the CEO captain was
 *  fed this turn (系统提示 / 对话历史 / 原始请求), shown turn-level on its bubble. Collapsible
 *  like 思考 (secondary to the answer). 决策②: the `system` block (verbatim 系统提示) is hidden
 *  — mobile has no 用量明细 reveal, so the full prompt stays a desktop power-user surface. */
function ReceivedContext({ blocks }: { blocks: ContextBlockWire[] }) {
  const visible = blocks.filter((b) => b.channel !== "system");
  if (visible.length === 0) return null;
  return (
    <details className="recv">
      <summary>收到的上下文 · {visible.length} 段</summary>
      <div className="recv-list">
        {visible.map((b, i) => (
          <div key={`${b.channel}-${i}`} className="recv-item">
            <div className="recv-head">
              <span className="recv-channel">
                {CONTEXT_CHANNEL_LABEL[b.channel] ?? b.channel}
              </span>
              {b.heading && <span className="recv-heading">{b.heading}</span>}
            </div>
            {b.body && <pre className="recv-body">{b.body}</pre>}
            {b.files.length > 0 && (
              <div className="recv-files">
                {b.files.map((f) => (
                  <span key={f} className="recv-file">
                    {f}
                  </span>
                ))}
              </div>
            )}
            {b.truncated && (
              <div className="recv-trunc">已截断（完整内容已传给 AI）</div>
            )}
          </div>
        ))}
      </div>
    </details>
  );
}

/** Tool execution phase → waiting-state chrome (transport-only `tool_use_progress`,
 *  read live via extractToolPhases) — so a slow tool reads「Searching / Fetching page /
 *  Running」rather than a bare「Running」status. Mirrors desktop (各端全新建; chrome, not
 *  shared logic). Unknown phase → generic「Working」. */
const TOOL_PHASE_TEXT: Record<ToolPhase, string> = {
  queued: "Queued",
  querying: "Searching",
  fallback: "Trying fallback",
  fetching: "Fetching page",
  reading: "Extracting",
  executing: "Running",
  blocked: "Network blocked",
};
const toolPhaseText = (phase: ToolPhase | undefined): string | null =>
  phase ? (TOOL_PHASE_TEXT[phase] ?? "Working") : null;

/** Seconds a tool has been running, ticking client-side from when this row first saw `running`
 *  (≈ the tool_use_start instant) — a liveliness cue for a BLOCKING tool (web_search) whose
 *  execution streams no incremental progress. Resets when not running. Mirrors desktop. */
function useRunningElapsed(running: boolean): number {
  const [elapsed, setElapsed] = useState(0);
  useEffect(() => {
    if (!running) {
      setElapsed(0);
      return;
    }
    const start = Date.now();
    const id = setInterval(
      () => setElapsed(Math.floor((Date.now() - start) / 1000)),
      1000,
    );
    return () => clearInterval(id);
  }, [running]);
  return elapsed;
}

/** Last path segment of a detail (a file 名 from a path / url); the whole string when it
 *  carries no separator (a query / pattern). Keeps a group summary compact. */
function baseName(detail: string): string {
  if (!detail) return "";
  const segs = detail.split(/[/\\]/);
  return segs[segs.length - 1] || detail;
}

type TimelineNode =
  | Exclude<ProcessStep, { kind: "tool" }>
  | { kind: "tool"; step: ToolStepData }
  | { kind: "tool-group"; tools: ToolStepData[] };

/** Coalesce consecutive tool steps into collapsible groups (前端UX设计.md §一B): a run of
 *  ≥2 adjacent tool steps folds into one `tool-group`, a lone tool stays inline, and
 *  reasoning/content break runs so chronological order is preserved. Mobile keeps its own
 *  copy of this fold — it is chrome, not a protocol fold (no conformance), so the desktop
 *  `groupToolRuns` is intentionally NOT imported (各端全新建 per cross-platform-frontend). */
function groupToolRuns(steps: ProcessStep[]): TimelineNode[] {
  const nodes: TimelineNode[] = [];
  let run: ToolStepData[] = [];
  const flush = () => {
    if (run.length === 0) return;
    nodes.push(
      run.length === 1
        ? { kind: "tool", step: run[0] }
        : { kind: "tool-group", tools: run },
    );
    run = [];
  };
  for (const s of steps) {
    if (s.kind === "tool") run.push(s);
    else {
      flush();
      nodes.push(s);
    }
  }
  flush();
  return nodes;
}

/** CEO 协调空转工具（与桌面 `COORDINATION_IDLE_TOOLS` 对称）。 */
function isCoordinationIdleTool(toolName: string): boolean {
  return toolName === "wait";
}

function isWaitIdleReasoning(steps: ProcessStep[], index: number): boolean {
  if (steps[index]?.kind !== "reasoning") return false;
  let i = index + 1;
  let sawWait = false;
  while (i < steps.length) {
    const s = steps[i];
    if (s.kind === "tool") {
      if (!isCoordinationIdleTool(s.tool_name)) return false;
      sawWait = true;
      i++;
      continue;
    }
    break;
  }
  if (sawWait) return true;
  let j = index - 1;
  sawWait = false;
  while (j >= 0) {
    const s = steps[j];
    if (s.kind === "tool") {
      if (!isCoordinationIdleTool(s.tool_name)) return false;
      sawWait = true;
      j--;
      continue;
    }
    break;
  }
  return sawWait;
}

/** View-layer omit：隐藏 wait 空转段（S4 Thought 降噪，对称桌面）。 */
function omitCoordinationIdleSteps(steps: ProcessStep[]): ProcessStep[] {
  if (steps.length === 0) return steps;
  let changed = false;
  const out: ProcessStep[] = [];
  for (let i = 0; i < steps.length; i++) {
    const s = steps[i];
    if (s.kind === "tool" && isCoordinationIdleTool(s.tool_name)) {
      changed = true;
      continue;
    }
    if (s.kind === "reasoning" && isWaitIdleReasoning(steps, i)) {
      changed = true;
      continue;
    }
    out.push(s);
  }
  return changed ? out : steps;
}

/** Header summary for a folded tool group: per-category counts in first-seen order
 *  (「Read file 6 · Edit file 2」), or each call's name/query when a single-category run is ≤3. */
function toolGroupSummary(tools: ToolStepData[]): string {
  const sameKind = tools.every((t) => t.tool_name === tools[0].tool_name);
  if (sameKind && tools.length <= 3) {
    const label = toolLabel(tools[0].tool_name);
    const names = tools.map((t) => baseName(toolDetail(t.arguments)));
    if (names.every(Boolean)) return `${label} ${names.join(" · ")}`;
  }
  const order: string[] = [];
  const counts = new Map<string, number>();
  for (const t of tools) {
    const label = toolLabel(t.tool_name);
    if (!counts.has(label)) order.push(label);
    counts.set(label, (counts.get(label) ?? 0) + 1);
  }
  return order.map((l) => `${l} ${counts.get(l)}`).join(" · ");
}

/** The single-agent inline timeline: content (Markdown), thinking (collapsible), and tool
 *  calls, in the order the model produced them. Consecutive tools coalesce into a
 *  collapsible {@link ToolGroup} (≥2); a lone tool stays an inline {@link ToolStep}.
 *  Append-only, so index keys are stable; the last content/reasoning text grows in place
 *  while streaming. */
function ProcessTimeline({
  steps,
  citations,
  evidenceLedger,
  team,
  asks,
  escalationSlots,
  hotTraces,
  stageCardTraces,
  toolPhases,
  graphAppendActKinds,
  graphAppendAuthorizedBy,
  onFill,
}: {
  steps: ProcessStep[];
  citations?: Citation[];
  evidenceLedger?: EvidenceLedgerEntry[];
  team?: TeamProjection;
  asks?: NonBlockingAsk[];
  escalationSlots?: Map<string, EscalationSlot>;
  hotTraces?: Map<string, HotDecisionTrace>;
  stageCardTraces?: Map<string, StageCardTrace>;
  toolPhases?: Map<string, ToolPhase>;
  graphAppendActKinds?: Map<string, string>;
  graphAppendAuthorizedBy?: Map<string, string>;
  onFill?: (text: string) => void;
}) {
  const nodes = groupToolRuns(omitCoordinationIdleSteps(steps));
  // Legacy turns whose persisted process predates the `team` marker still carry a team
  // (re-folded from events) — render it once at the top so the graph never vanishes.
  const hasTeamMarker = steps.some((s) => s.kind === "team");
  return (
    <div className="timeline">
      {team && !hasTeamMarker ? <TeamView {...team} /> : null}
      {nodes.map((node, i) => {
        if (node.kind === "content")
          return (
            <div
              // biome-ignore lint/suspicious/noArrayIndexKey: timeline is an append-only stream; segments never reorder, so the index is stable identity
              key={i}
              className="process-narration"
            >
              <Markdown
                content={node.text}
                citations={citations}
                evidenceLedger={evidenceLedger}
              />
            </div>
          );
        if (node.kind === "reasoning")
          // biome-ignore lint/suspicious/noArrayIndexKey: timeline is an append-only stream; segments never reorder, so the index is stable identity
          return <Reasoning key={i} text={node.text} />;
        if (node.kind === "team")
          return team ? (
            <TeamView key={`team-${node.execution_id}`} {...team} />
          ) : null;
        // 跨回合同图追加：追加回合只渲染锚点（宿主气泡仍挂完整 TeamView）。
        if (node.kind === "graph_append") {
          const actKind = graphAppendActKinds?.get(node.execution_id);
          const auth = graphAppendAuthorizedBy?.get(node.execution_id);
          return (
            <div
              key={`graph-append-${node.execution_id}-${node.host_message_id}`}
              className="graph-append-anchor"
            >
              {graphAppendAnchorLabel(node.added_count, actKind, auth)}
            </div>
          );
        }
        // 非阻塞提问卡 (ask_user blocking=false): resolve the `ask` marker to its card at
        // its chronological slot, content looked up by ask_id from the transport-only
        // `asks` side channel (extractAsks). No content (single-agent history / no onFill)
        // → the marker no-ops, exactly like desktop.
        if (node.kind === "ask") {
          const ask = asks?.find((a) => a.id === node.ask_id);
          return ask && onFill ? (
            <NonBlockingAskCard key={ask.id} ask={ask} onFill={onFill} />
          ) : null;
        }
        if (node.kind === "escalation") {
          const slot = escalationSlots?.get(node.escalation_id);
          if (!slot) return null;
          const live =
            slot.esc.status === "pending" &&
            team?.escalationsInteractive &&
            team.conversationId
              ? slot.id
              : undefined;
          if (live && team?.conversationId) {
            return (
              <EscalationAnswer
                key={slot.id}
                esc={slot.esc}
                escalationId={live}
                conversationId={team.conversationId}
              />
            );
          }
          const detail = escalationDetail(slot.esc);
          return (
            <div key={slot.id} className="run-escalation">
              <span className="run-escalation-q">↑ {slot.esc.question}</span>
              {detail && <span className="run-escalation-a">{detail}</span>}
            </div>
          );
        }
        // 热审批 / 委派授权痕迹 (D3): resolved 后在 required 时刻槽显轻状态行；
        // pending 标记在、行不显（操作面在 PauseCard）。对齐桌面 HotDecisionTrace。
        if (node.kind === "approval") {
          const t = hotTraces?.get(node.approval_id);
          if (!t?.resolved) return null;
          const tool = t.toolName ? toolLabel(t.toolName) : "工具";
          return (
            <div key={`appr-${node.approval_id}`} className="hot-trace">
              ✓ {t.denied ? `已拒绝 · ${tool}` : `已批准 · ${tool}`}
            </div>
          );
        }
        if (node.kind === "delegation_authorization") {
          const t = hotTraces?.get(node.authorization_id);
          if (!t?.resolved) return null;
          return (
            <div key={`dauth-${node.authorization_id}`} className="hot-trace">
              ✓ {t.denied ? "已拒绝委派授权" : "已授权开工"}
            </div>
          );
        }
        if (node.kind === "stage_card") {
          const t = stageCardTraces?.get(node.stage_card_id);
          if (!t || t.outcome === "pending") return null;
          const label =
            t.outcome === "orphaned"
              ? "推进卡 · 已失效"
              : t.decision === "research_first"
                ? "推进卡 · 已选补充调研"
                : "推进卡 · 已开辩";
          return (
            <div key={`sc-${node.stage_card_id}`} className="hot-trace">
              {t.outcome === "orphaned" ? "✕ " : "✓ "}
              {label}
            </div>
          );
        }
        // checkpoint·plan_review markers anchor desktop cards; mobile owns these blocking
        // interactions via its PauseCard surface, so they render nothing inline.
        if (
          node.kind === "checkpoint" ||
          node.kind === "plan_review" ||
          node.kind === "team_preview"
        )
          return null;
        if (node.kind === "tool-group")
          return (
            <ToolGroup
              key={node.tools[0].id}
              tools={node.tools}
              toolPhases={toolPhases}
            />
          );
        if (node.kind === "rework")
          return (
            // biome-ignore lint/suspicious/noArrayIndexKey: timeline is an append-only stream; segments never reorder, so the index is stable identity
            <span key={`rework-${i}`} className="rework-chip">
              引用/格式核验后已重写
            </span>
          );
        if (node.kind !== "tool") return null;
        return (
          <ToolStep
            key={node.step.id}
            step={node.step}
            phase={toolPhases?.get(node.step.id)}
          />
        );
      })}
    </div>
  );
}

/** Collapsible thinking block (collapsed by default — secondary to the answer). */
function Reasoning({ text }: { text: string }) {
  return (
    <details className="reasoning">
      <summary>思考</summary>
      <Markdown content={text} muted />
    </details>
  );
}

/** ≥2 consecutive `web_search` — flatten (no outer <details>). Each search row already
 *  shows query + count; mirroring desktop ToolLineGroup's web_search flat path. */
function isWebSearchFlatGroup(tools: ToolStepData[]): boolean {
  return tools.length >= 2 && tools.every((t) => t.tool_name === "web_search");
}

/** A folded run of ≥2 consecutive tool calls (前端UX设计.md §一B; the mobile mirror of the
 *  desktop ProcessToolGroup). A collapsed-by-default <details> — the same fold idiom as 思考
 *  (mobile has no streaming-aware auto-expand for either) — whose summary is the per-category
 *  count / file names plus any 失败 count; expands to the unchanged per-tool {@link ToolStep}
 *  rows, each still openable to its own result. Pure web_search runs skip the shell. */
function ToolGroup({
  tools,
  toolPhases,
}: {
  tools: ToolStepData[];
  toolPhases?: Map<string, ToolPhase>;
}) {
  if (isWebSearchFlatGroup(tools)) {
    return (
      <div className="tool-group-flat">
        {tools.map((t) => (
          <ToolStep key={t.id} step={t} phase={toolPhases?.get(t.id)} />
        ))}
      </div>
    );
  }
  const errorCount = tools.reduce(
    (n, t) =>
      n +
      (t.status === "error" &&
      !isFileReadCeilingGuidance(t.tool_name, t.result) &&
      !isVerifyBudgetExceeded(t.display)
        ? 1
        : 0),
    0,
  );
  return (
    <details className="tool-group">
      <summary>
        <span className="tool-group-summary">{toolGroupSummary(tools)}</span>
        {errorCount > 0 && (
          <span className="tool-group-error">{errorCount} failed</span>
        )}
      </summary>
      <div className="tool-group-body">
        {tools.map((t) => (
          <ToolStep key={t.id} step={t} phase={toolPhases?.get(t.id)} />
        ))}
      </div>
    </details>
  );
}

const TOOL_STATUS: Record<ToolStepData["status"], string> = {
  running: "Running",
  success: "Done",
  error: "Failed",
};

/** A tool call: English name (+ its arg detail) · status, expandable to its full arguments and
 *  result. While running, the status shows the coarse phase (Searching / Queued / Trying fallback,
 *  from the live `phase`) + an elapsed timer — a live waiting cue instead of a static「Running」. */
function ToolStep({
  step,
  phase,
}: {
  step: ToolStepData;
  phase?: ToolPhase;
}) {
  const [open, setOpen] = useState(false);
  const args = Object.keys(step.arguments).length > 0 ? step.arguments : null;
  const detail = toolDetail(step.arguments);
  const running = step.status === "running";
  const ceilingGuidance =
    step.status === "error" &&
    (isFileReadCeilingGuidance(step.tool_name, step.result) ||
      isVerifyBudgetExceeded(step.display));
  const elapsed = useRunningElapsed(running);
  const doneStatus = ceilingGuidance
    ? isVerifyBudgetExceeded(step.display)
      ? "验证未完成"
      : "Notice"
    : TOOL_STATUS[step.status];
  const runningStatus = running
    ? [
        toolPhaseText(phase) ?? TOOL_STATUS.running,
        elapsed >= 1 ? `${elapsed}s` : null,
      ]
        .filter(Boolean)
        .join(" · ")
    : doneStatus;
  const shellClass = ceilingGuidance
    ? "tool tool-guidance"
    : `tool tool-${step.status}`;
  return (
    <div className={shellClass}>
      <button
        type="button"
        className="tool-head"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="tool-name">
          {toolLabel(step.tool_name)}
          {detail && <span className="tool-detail">{detail}</span>}
        </span>
        <span className="tool-status">{runningStatus}</span>
      </button>
      {open && (args || step.result != null) && (
        <div className="tool-body">
          {isVerifyBudgetExceeded(step.display) && (
            <div className="tool-incomplete">验证未完成（预算耗尽）</div>
          )}
          {args && (
            <pre className="tool-pre">{JSON.stringify(args, null, 2)}</pre>
          )}
          {step.result != null && step.result !== "" && (
            <pre className="tool-pre">{step.result}</pre>
          )}
        </div>
      )}
    </div>
  );
}

const CITATION_TIER_LABEL: Record<string, string> = {
  official: "官方",
  media: "媒体",
  unknown: "待评",
  weak: "弱源",
};

/** The web sources consulted for this message (citations event / persisted citations). */
function Citations({ items }: { items: Citation[] }) {
  return (
    <div className="cites">
      <div className="cites-title">来源</div>
      {items.map((c, i) => {
        const tierLabel = c.tier ? CITATION_TIER_LABEL[c.tier] : null;
        return (
          <a
            key={`${c.url}-${i}`}
            className="cite"
            href={c.url}
            target="_blank"
            rel="noreferrer"
          >
            <span className="cite-n">{i + 1}</span>
            <span className="cite-text">
              <span className="cite-title-row">
                <span className="cite-title">{c.title || c.url}</span>
                {c.id ? (
                  <span className="cite-id" title={`台账 ${c.id}`}>
                    {c.id}
                  </span>
                ) : null}
                {tierLabel && (
                  <span
                    className={`cite-tier cite-tier-${c.tier}`}
                    title={`来源可信度：${tierLabel}`}
                  >
                    {tierLabel}
                  </span>
                )}
              </span>
              {c.site && <span className="cite-site">{c.site}</span>}
            </span>
          </a>
        );
      })}
    </div>
  );
}
