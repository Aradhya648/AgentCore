// The multi-agent team view for the mobile client (前端技术与架构 §七 · 多 Agent 团队视图).
//
// A mobile-native, VERTICAL reduction of the desktop React-Flow team graph
// (InlineTeamGraph / GraphView): the same ProjectedTurn.{agents, runs, progress} fields,
// no canvas / ELK / scrubber. Consumed IDENTICALLY by live turns (fold(turn.events)) and
// history replay (fold(MessageDetail.runs.events)) — there is no second data path.
//
// The `captain` run is the chat bubble itself (the CEO's reply streams into the message),
// so it is omitted here; only the delegated `agent` workers are listed. The three desktop
// relations collapse to mobile-appropriate cues: DAG order = list order, the delegate tree
// (`parentRunId`) = indentation, the revision chain (`revision >= 2`) = a badge. Debate
// (`stance`) shows a pill per card rather than pro/con columns (too wide for a phone).
import {
  type EscalationUserDecision,
  decideEscalation,
} from "@/api/interaction";
import { EvidenceLedgerProvider } from "@/components/EvidenceLedgerContext";
import { Markdown } from "@/components/Markdown";
import { Modal } from "@/components/Modal";
import {
  CONTEXT_CHANNEL_LABEL,
  runPhaseLabel,
  toolDetail,
  toolLabel,
  toolPhaseText,
} from "@/components/assistantLabels";
import { buildLedgerMap } from "@/lib/evidenceLedger";
import { isFileReadCeilingGuidance } from "@/lib/fileReadCeiling";
import type { RunToolCall } from "@/protocol/fold";
import { actAuthorizedByLabel } from "@/protocol/fold";
import type {
  ContextBlockWire,
  DeliveryStatusPayload,
  EvidenceLedgerEntry,
} from "@agentcore/contract-types";
import type {
  ActKind,
  ProjectedAct,
  ProjectedAgent,
  ProjectedRun,
  ProjectedTeamNote,
  RunDebrief,
  RunEscalation,
  RunStatus,
  TurnStatus,
} from "@agentcore/protocol-conformance";
import { type ReactNode, useMemo, useState } from "react";

/** 幕 kind → 列表分组头短标签（无 title 时回落；手机列表语言，非桌面幕分带）。 */
const ACT_KIND_LABEL: Record<ActKind, string> = {
  multi_agent: "调研",
  debate: "辩论",
};

function actSectionLabel(act: ProjectedAct | undefined, actId: string): string {
  if (act?.title?.trim()) return act.title.trim();
  if (act?.kind) return ACT_KIND_LABEL[act.kind] ?? act.kind;
  return actId;
}

type CheckpointDecision = NonNullable<ProjectedRun["checkpoint"]>["decision"];

/**
 * 团队便签墙默认展开规则（对齐桌面/画布，手机端自写一份，不共享桌面实现）：
 * 便签为空 → 不渲染（调用方短路）；运行中且存在 active 便签 → 默认展开；否则默认收起。
 */
export function teamNotesDefaultExpanded(
  status: TurnStatus | null | undefined,
  notes: readonly ProjectedTeamNote[],
): boolean {
  if (notes.length === 0) return false;
  if (status !== "running") return false;
  return notes.some((n) => n.status === "active");
}

/** 团队便签墙 (§2.2 通) note kind → 中文 label + css class. `decision` (我定了) is a choice others
 * depend on (an interface / field name / format / naming); `heads_up` (提个醒) is a pitfall /
 * discovery; `claim` (我领了) is a piece of work / file this worker is taking, so a sibling doesn't
 * duplicate it. Mirrors the backend NoteWall labels (runtime/runs/notewall.py); an unknown kind
 * falls back to 提个醒. */
const NOTE_STATUS_LABEL: Record<string, string> = {
  superseded: "已更新",
  voided: "已作废",
};

const NOTE_KIND_LABEL: Record<string, string> = {
  decision: "约定",
  heads_up: "提醒",
  claim: "认领",
};

const NOTE_KIND_CLASS: Record<string, string> = {
  decision: "kind-decision",
  heads_up: "kind-headsup",
  claim: "kind-claim",
};

const RUN_STATUS: Record<RunStatus, { label: string; tone: string }> = {
  pending: { label: "排队中", tone: "muted" },
  running: { label: "进行中", tone: "run" },
  completed: { label: "完成", tone: "ok" },
  failed: { label: "失败", tone: "err" },
  cancelled: { label: "已停止", tone: "muted" },
  skipped: { label: "未执行", tone: "muted" },
};

/** 证人席位根：开赛挂席、点名才作答 — pending→待命，skipped→未传唤。
 *  running + `run.phase` → 相位文案（不再一律「进行中」/「思考中」）。 */
function runStatusLabel(
  status: RunStatus,
  run: {
    group?: string | null;
    continuesRunId?: string | null;
    phase?: ProjectedRun["phase"];
  },
): { label: string; tone: string } {
  const base = RUN_STATUS[status];
  const witnessSeat =
    run.group === "debate:witness" && run.continuesRunId == null;
  if (witnessSeat) {
    if (status === "pending") return { label: "待命", tone: "muted" };
    if (status === "skipped") return { label: "未传唤", tone: "muted" };
    return base;
  }
  if (status === "running") {
    const phase = runPhaseLabel(run.phase);
    if (phase) return { label: phase, tone: "run" };
  }
  return base;
}

function formatDuration(ms: number): string {
  if (ms < 1000) return `${ms}ms`;
  const s = ms / 1000;
  if (s < 60) return `${s.toFixed(1)}s`;
  return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s`;
}

function checkpointLabel(decision: CheckpointDecision): string {
  switch (decision) {
    case "adjust":
      return "已调整";
    case "stop":
      return "已停止";
    case "timeout":
      return "已超时";
    default:
      return "已放行";
  }
}

function lastLine(text: string | undefined): string | null {
  if (!text) return null;
  const lines = text.trimEnd().split("\n");
  return lines[lines.length - 1] || null;
}

/** The read-only one-liner under an escalation's question, by lifecycle. */
export function escalationDetail(esc: RunEscalation): string | null {
  if (esc.status === "resolved" && esc.answer) return `已答复：${esc.answer}`;
  if (esc.status === "assumed")
    return esc.assumption ? `按假设继续：${esc.assumption}` : null;
  if (esc.status === "timed_out")
    return esc.assumption ? `超时回落假设：${esc.assumption}` : null;
  return esc.assumption ? `暂用假设：${esc.assumption}` : null;
}

export function TeamView({
  agents,
  runs,
  progress,
  acts = [],
  teamNotes = [],
  deliveryStatus = null,
  status,
  conversationId: _conversationId = null,
  pendingEscalations: _pendingEscalations,
  escalationsInteractive: _escalationsInteractive = false,
  runToolCalls,
  workerToolPhases,
  evidenceLedger = [],
}: {
  agents: ProjectedAgent[];
  runs: ProjectedRun[];
  progress: { completed: number; total: number };
  /** 幕序列（批 A4）：≥2 幕时列表按幕插分组头；单幕 / 缺省保持既有扁平列表。 */
  acts?: ProjectedAct[];
  /** 团队便签墙 (§2.2 通): notes workers broadcast to their concurrent siblings this turn. */
  teamNotes?: ProjectedTeamNote[];
  /** 交付状态（`delivery_status`）：partial / blocked 一句轻提示；delivered / notes 静默。
   *  产物清单仍由 ChatPage + FileArtifactsCard 承载。 */
  deliveryStatus?: DeliveryStatusPayload | null;
  /** Turn lifecycle from ProjectedTurn — drives team-notes default expand/collapse. */
  status?: TurnStatus | null;
  /** 阻塞式求决策 (②): present on a live multi-agent turn so a worker's pending escalation
   *  renders as an actionable answer card. */
  conversationId?: string | null;
  /** runId → pending escalation id from ProjectedTurn.interactions (P3 · 按 id 精确提交). */
  pendingEscalations?: Map<string, string>;
  /** Live turn → the pending escalation is answerable over the open stream (else read-only). */
  escalationsInteractive?: boolean;
  /** 队员工具明细 (RunDetail · 工具调用): runId → the worker's tool calls (transport-only sibling
   *  extractRunToolCalls). Fed to the run-detail panel; absent → the panel shows no tool section. */
  runToolCalls?: Map<string, RunToolCall[]>;
  /** Worker `tool_use_progress` (run_id): runId → live EXECUTION phase + tool name (transport-only
   *  sibling {@link import("@/protocol/fold").extractWorkerToolPhases}). */
  workerToolPhases?: Map<string, { phase: string; toolName: string }>;
  /** 场级证据台账（`extractEvidenceLedger`）：辩论发言徽章 `#eN` 解析（O7）。 */
  evidenceLedger?: EvidenceLedgerEntry[];
}) {
  // 深度检视单个队员 (RunDetail): tapping a RunCard opens a detail panel pinned to this run. The
  // panel navigates to another run (修订链切换 / 关系跳转) by swapping the selected id — the run
  // list is the same ProjectedTurn slice whether live or replayed.
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  const workers = runs.filter((r) => r.kind !== "captain");
  const ledgerMap = useMemo(
    () => (evidenceLedger.length ? buildLedgerMap(evidenceLedger) : null),
    [evidenceLedger],
  );
  const actById = useMemo(() => new Map(acts.map((a) => [a.actId, a])), [acts]);
  if (workers.length === 0) return null;
  const selectedRun = selectedRunId
    ? (runs.find((r) => r.id === selectedRunId) ?? null)
    : null;

  const multiAct = acts.length >= 2;
  // 单幕辩论：头部保留「辩论」徽标；多幕时改由分组头表达，避免整队被扁平标成辩论。
  const isDebate =
    !multiAct && (acts[0]?.kind === "debate" || workers.some((r) => r.stance));
  const pct =
    progress.total > 0 ? (progress.completed / progress.total) * 100 : 0;
  const notesDefaultOpen = teamNotesDefaultExpanded(status, teamNotes);

  // Indent a nested delegate by how many worker parents it chains through (stage-2 子任务).
  const depthOf = (run: ProjectedRun): number => {
    let depth = 0;
    let parentId = run.parentRunId;
    const seen = new Set<string>([run.id]);
    while (parentId && !seen.has(parentId)) {
      seen.add(parentId);
      const parent = workers.find((r) => r.id === parentId);
      if (!parent) break;
      depth += 1;
      parentId = parent.parentRunId;
    }
    return depth;
  };

  const runCards: ReactNode[] = [];
  let lastActId: string | null = null;
  for (const run of workers) {
    const actId = run.actId || "act-1";
    if (multiAct && actId !== lastActId) {
      lastActId = actId;
      const act = actById.get(actId);
      runCards.push(
        <div key={`act-head-${actId}`} className="team-act-head">
          <span className="team-act-title">{actSectionLabel(act, actId)}</span>
          {act?.kind && (
            <span className="team-act-kind">
              {ACT_KIND_LABEL[act.kind] ?? act.kind}
            </span>
          )}
          {actAuthorizedByLabel(act?.authorizedBy) ? (
            <span className="team-act-auth">
              {actAuthorizedByLabel(act?.authorizedBy)}
            </span>
          ) : null}
        </div>,
      );
    }
    runCards.push(
      <RunCard
        key={run.id}
        run={run}
        agent={agents.find((a) => a.id === run.agentId)}
        depth={depthOf(run)}
        continuationIndex={continuationIndexOf(workers, run)}
        workerToolPhase={workerToolPhases?.get(run.id)}
        onOpen={() => setSelectedRunId(run.id)}
      />,
    );
  }

  return (
    <EvidenceLedgerProvider ledger={ledgerMap}>
      <div className="team">
        <div className="team-head">
          <span className="team-count">
            团队 {progress.completed}/{progress.total}
          </span>
          {multiAct ? (
            <span className="team-tag">{acts.length} 幕</span>
          ) : isDebate ? (
            <span className="team-tag">辩论</span>
          ) : null}
        </div>
        <div className="team-bar">
          <span className="team-bar-fill" style={{ width: `${pct}%` }} />
        </div>
        <div className="team-runs">{runCards}</div>
        {/* 团队便签墙 (§2.2 通): the one-line decisions / heads-ups workers broadcast to their
          concurrent siblings this turn — the visible, glass-box face of the note wall (贴事实·
          不要求回应, NOT a chat). Shown attributed (谁贴的) + kind-tagged (我定了 / 提个醒), in post
          order. Empty (the common case) renders nothing. Collapsible like 思考/工具组 (<details>):
          running + active note → default open; finished/stopped → collapsed「团队便签 N」. Remount
          via key when the default flips so turn completion re-applies the collapsed default. */}
        {/* 交付轻提示（对齐桌面 DeliveryStatusMount）：delivered / notes 静默；
          partial / blocked 一句 summary；无验收卡、无动作、无缺口明细。 */}
        {deliveryStatus ? <DeliverySection status={deliveryStatus} /> : null}
        {teamNotes.length > 0 && (
          <TeamNotesWall
            key={notesDefaultOpen ? "open" : "shut"}
            notes={teamNotes}
            defaultOpen={notesDefaultOpen}
          />
        )}
        {/* 深度检视单个队员 (RunDetail): the detail panel for the tapped run — a native <dialog>
          bottom sheet. Navigating (修订链切换 / 关系跳转) swaps `selectedRunId` so the SAME open
          dialog re-renders in place (no remount flash); unmounting (→ null) closes it. */}
        {selectedRun && (
          <RunDetailPanel
            run={selectedRun}
            agents={agents}
            runs={runs}
            toolCalls={runToolCalls?.get(selectedRun.id) ?? []}
            onSelect={setSelectedRunId}
            onClose={() => setSelectedRunId(null)}
          />
        )}
      </div>
    </EvidenceLedgerProvider>
  );
}

/** 交付轻提示（对齐桌面 DeliveryStatusMount）：砍验收大卡与卡上动作；
 *  delivered / notes 静默；partial / blocked 最多一句。产物清单不在此。 */
function DeliverySection({ status }: { status: DeliveryStatusPayload }) {
  if (status.state !== "partial" && status.state !== "blocked") return null;
  const text =
    status.summary.trim() ||
    (status.state === "blocked" ? "交付未满足" : "部分交付未满足");
  return (
    <p
      className="delivery-shortfall-hint"
      data-testid="delivery-shortfall-hint"
    >
      {text}
    </p>
  );
}

/** Collapsible team-notes wall — remounted by the parent when `defaultOpen` flips so the
 *  running→finished transition re-applies the collapsed default (same key trick as desktop). */
function TeamNotesWall({
  notes,
  defaultOpen,
}: {
  notes: ProjectedTeamNote[];
  defaultOpen: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  return (
    <details
      className="team-notes"
      open={open}
      onToggle={(e) => setOpen((e.target as HTMLDetailsElement).open)}
    >
      <summary className="team-notes-head">团队便签 {notes.length}</summary>
      <div className="team-notes-body">
        {notes.map((note) => {
          // 便签会过期 → supersession (§2.2): a 改写/作废'd note is struck + dimmed with a status
          // pill, so a stale decision can't be mistaken for current truth. `active` → no pill.
          const statusLabel = NOTE_STATUS_LABEL[note.status];
          return (
            <div
              key={note.noteId}
              className={`team-note${statusLabel ? " team-note-stale" : ""}`}
            >
              <div className="team-note-meta">
                <span
                  className={`team-note-kind ${
                    NOTE_KIND_CLASS[note.kind] ?? "kind-headsup"
                  }`}
                >
                  {NOTE_KIND_LABEL[note.kind] ?? "提醒"}
                </span>
                <span className="team-note-author">
                  {note.role || note.agentId}
                </span>
                {statusLabel && (
                  <span
                    className={`team-note-status ${
                      note.status === "voided"
                        ? "status-voided"
                        : "status-superseded"
                    }`}
                  >
                    {statusLabel}
                  </span>
                )}
              </div>
              <div className="team-note-text">{note.text}</div>
            </div>
          );
        })}
      </div>
    </details>
  );
}

/** The status / role pills on a run (stance / 续 ×N / 计划已调整 / 子任务 / checkpoint / 上报),
 *  shared by the {@link RunCard} peek and the {@link RunDetailPanel} header so the two read the
 *  same. `isChild` (a delegated sub-task) is passed in — the card knows it from graph depth, the
 *  panel from the run's parent. Renders nothing when the run has no pill. */
function RunPills({
  run,
  isChild,
  continuationIndex = 0,
}: {
  run: ProjectedRun;
  isChild: boolean;
  continuationIndex?: number;
}) {
  const hasPill =
    run.stance ||
    continuationIndex >= 1 ||
    run.revised ||
    isChild ||
    run.checkpoint ||
    run.escalations.length > 0;
  if (!hasPill) return null;
  return (
    <div className="run-tags">
      {run.stance && (
        <span className="run-pill">
          {run.stance === "pro" ? "正方" : "反方"}
        </span>
      )}
      {continuationIndex >= 1 && (
        <span className="run-pill">续 ×{continuationIndex}</span>
      )}
      {/* 「计划已调整」轻痕迹 (设计 §7.2): the CEO autonomously re-bound (bind) / re-steered
          (steer) this node mid-flight — a non-interrupting cue mirroring the desktop node badge. */}
      {run.revised && <span className="run-pill">计划已调整</span>}
      {isChild && <span className="run-pill">子任务</span>}
      {/* 拍板类不用琥珀（2026-07 拍板）：pending「需要你」= 蓝 pill-act，已决记录 = 中性
          run-pill（对齐桌面 checkpointBadge：pending primary / settled muted）。 */}
      {run.checkpoint && (
        <span
          className={`run-pill${run.checkpoint.status === "pending" ? " pill-act" : ""}`}
        >
          {run.checkpoint.status === "pending"
            ? "待放行"
            : checkpointLabel(run.checkpoint.decision)}
        </span>
      )}
      {/* 升级实时可见: a worker flagged a blocker for the CEO — a 待裁决 cue mirroring the desktop
          node ⚠️ badge; the full ask renders below / in the panel. Pending = 蓝（待你拍板），
          其余（已答复 / 按假设 / 非阻塞上报）= 中性记录. */}
      {run.escalations.length > 0 && (
        <span
          className={`run-pill${run.escalations.some((e) => e.status === "pending") ? " pill-act" : ""}`}
        >
          上报{run.escalations.length > 1 ? ` ${run.escalations.length}` : ""}
        </span>
      )}
    </div>
  );
}

function RunCard({
  run,
  agent,
  depth,
  continuationIndex = 0,
  workerToolPhase,
  onOpen,
}: {
  run: ProjectedRun;
  agent: ProjectedAgent | undefined;
  depth: number;
  continuationIndex?: number;
  /** Live worker tool EXECUTION phase (transport-only `tool_use_progress` with run_id). */
  workerToolPhase?: { phase: string; toolName: string };
  /** 深度检视 (RunDetail): tap the card summary to open this run's detail panel. */
  onOpen: () => void;
}) {
  const st = runStatusLabel(run.status, run);
  const name = run.role ?? agent?.role ?? run.agentId;
  // Running: the worker's streaming tail (tool composing > tool executing > output last line).
  // Settled: its one-line summary. Both come off the same fold whether live or replayed.
  const preview =
    run.status === "running"
      ? agent?.toolProgress
        ? `Composing ${toolLabel(agent.toolProgress.toolName)}…`
        : workerToolPhase
          ? `${toolPhaseText(workerToolPhase.phase) ?? "Working"} · ${toolLabel(workerToolPhase.toolName)}`
          : lastLine(agent?.output)
      : run.outputSummary;

  return (
    <div
      className={`run run-${st.tone}`}
      style={depth > 0 ? { marginInlineStart: depth * 12 } : undefined}
    >
      {/* 深度检视入口: the whole card summary is ONE tap target opening the run detail. The
          escalation answer card (textarea / 提交 / 按假设继续) is a SIBLING below, OUTSIDE this
          button, so its interactions are never hijacked by the open-detail tap (架构约束①). */}
      <button type="button" className="run-open" onClick={onOpen}>
        <div className="run-head">
          <span className="run-name">{name}</span>
          <span className={`run-badge badge-${st.tone}`}>{st.label}</span>
        </div>
        <RunPills
          run={run}
          isChild={depth > 0}
          continuationIndex={continuationIndex}
        />
        {run.task && <div className="run-task">{run.task}</div>}
        {preview && <div className="run-preview">{preview}</div>}
        {run.error && <div className="run-error">{run.error}</div>}
        {run.status === "completed" && run.durationMs != null && (
          <div className="run-foot">{formatDuration(run.durationMs)}</div>
        )}
      </button>
      {/* 升级卡已迁独立时间线标记（统一时间线二期 D2）；节点仍保留 上报 pill。 */}
    </div>
  );
}

/** 阻塞式求决策「待你拍板」(②): a worker SUSPENDED on a blocking escalate is awaiting the user
 *  over the open stream. Free-text answer + 提交 / 按假设继续 (== timeout disposition), mirroring
 *  the mobile PauseCard's reduced surface (structured forks fold to prose). decideEscalation
 *  POSTs to the unified resolve endpoint; the stream's `escalation_resolved` then folds this
 *  run's escalation to resolved/timeout and unmounts the card (so busy stays true on success).
 *  统一时间线二期: rendered at the escalation process marker (not under TeamView run cards). */
export function EscalationAnswer({
  esc,
  escalationId,
  conversationId,
}: {
  esc: RunEscalation;
  escalationId: string;
  conversationId: string;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [note, setNote] = useState("");

  async function decide(decision: EscalationUserDecision) {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await decideEscalation(conversationId, escalationId, decision);
      // Leave busy=true on success: escalation_resolved drops `pending` and unmounts this.
    } catch (e) {
      setErr(e instanceof Error ? e.message : "提交失败");
      setBusy(false);
    }
  }

  return (
    <div className="run-escalation run-escalation-live">
      <span className="run-escalation-q">↑ {esc.question}</span>
      {esc.assumption && (
        <span className="run-escalation-a">
          未答则按此继续：{esc.assumption}
        </span>
      )}
      <textarea
        className="run-escalation-note"
        rows={2}
        value={note}
        disabled={busy}
        placeholder="输入你的决定（留空则点「按假设继续」）"
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="run-escalation-actions">
        <button
          type="button"
          className="esc-btn esc-btn-primary"
          disabled={busy || !note.trim()}
          onClick={() => void decide({ kind: "answer", answer: note.trim() })}
        >
          提交
        </button>
        <button
          type="button"
          className="esc-btn esc-btn-neutral"
          disabled={busy}
          onClick={() => void decide({ kind: "use_assumption" })}
        >
          按假设继续
        </button>
      </div>
      {busy && <span className="run-escalation-busy">处理中…</span>}
      {err && <span className="run-error">{err}</span>}
    </div>
  );
}

// —— 深度检视单个队员 · RunDetail (对齐桌面 RunDetail 抽屉的信息，手机原生重表达) ——

/** 思考开关 → 中文 label (mirrors desktop reasoningMeta): off / 开启. */
function reasoningLabel(thinking: boolean): string {
  if (!thinking) return "关闭";
  return "开启";
}

/** Compact token count (1.2k / 3.4M) — the run-detail 资源 is a power detail, kept scannable. */
function formatCompact(n: number): string {
  if (n < 1000) return String(n);
  if (n < 1_000_000) return `${(n / 1000).toFixed(1)}k`;
  return `${(n / 1_000_000).toFixed(1)}M`;
}

/** Integer nano-CNY (1 元 = 1e9) → ¥ caption; all-zero renders「—」(§7.5), never「¥0.00」.
 *  BYOK estimates use ≈ prefix. */
function formatCostYuan(nanoCny: number, estimated = false): string {
  const yuan = nanoCny / 1e9;
  if (yuan <= 0) return "—";
  const body = yuan < 0.01 ? "<¥0.01" : `¥${yuan.toFixed(yuan < 0.1 ? 4 : 2)}`;
  return estimated ? `≈${body} 自带密钥·估算` : body;
}

interface RevisionVersion {
  version: number;
  run: ProjectedRun;
}

/** 同根接续链上的序号（1-based）；非接续为 0。 */
function continuationIndexOf(runs: ProjectedRun[], run: ProjectedRun): number {
  if (run.continuesRunId == null) return 0;
  const siblings = runs.filter((r) => r.continuesRunId === run.continuesRunId);
  const i = siblings.findIndex((r) => r.id === run.id);
  return i >= 0 ? i + 1 : 1;
}
function revisionChainFor(
  runs: ProjectedRun[],
  runId: string,
): RevisionVersion[] | null {
  const run = runs.find((r) => r.id === runId);
  if (!run) return null;
  const originalId = run.continuesRunId ?? run.id;
  const original = runs.find((r) => r.id === originalId);
  if (!original) return null;
  const continuations = runs.filter((r) => r.continuesRunId === originalId);
  if (continuations.length === 0) return null;
  return [
    { version: 1, run: original },
    ...continuations.map((r, i) => ({ version: i + 2, run: r })),
  ];
}

/**
 * 深度检视单个队员 (RunDetail): a mobile-native bottom-sheet reduction of the desktop RunDetail
 * drawer, pinned to one worker run. Sections mirror the desktop order (头部 → 任务/本轮焦点 →
 * 轮次/修订链 → 升级 → 收到的上下文 → 思考 → 工具明细 → 输出/交接简报 → 资源 → 关系); 诊断/审计
 * are intentionally omitted (power-user desktop surfaces). Reads only the fold's ProjectedTurn
 * fields + the transport-only {@link RunToolCall} side channel — no desktop import, no new fold.
 * Navigates to another run (修订链切换 / 关系跳转) via `onSelect`, which re-pins the panel.
 */
function RunDetailPanel({
  run,
  agents,
  runs,
  toolCalls,
  onSelect,
  onClose,
}: {
  run: ProjectedRun;
  agents: ProjectedAgent[];
  runs: ProjectedRun[];
  toolCalls: RunToolCall[];
  onSelect: (runId: string) => void;
  onClose: () => void;
}) {
  const agent = agents.find((a) => a.id === run.agentId);
  const st = runStatusLabel(run.status, run);
  const name = run.role ?? agent?.role ?? run.agentId;
  const reasoning = agent?.reasoning ?? "";
  const output = agent?.output ?? "";
  const isChild = run.parentRunId != null && run.continuesRunId == null;

  // 本轮焦点: a 续写 run (辩论逐轮 / 同人接续) was fed round-scoped context — show its 本轮焦点 in
  // place of the (inherited) task, mirroring the desktop RunDetail.
  const roundFocus =
    run.continuesRunId != null
      ? run.receivedContext.find((b) => b.channel === "round_focus")?.body
      : undefined;

  // 收到的上下文: the worker-side blocks it was fed. Hide the verbatim 系统提示 (决策②: mobile has
  // no full-prompt reveal) — a worker's blocks are task / deliverable / dependency context anyway.
  const contextBlocks = run.receivedContext.filter(
    (b) => b.channel !== "system",
  );

  const chain = revisionChainFor(runs, run.id);
  const isDebateChain = chain?.some((v) => v.run.stance != null) ?? false;

  // 关系: 依赖 (upstream) / 后续 (downstream) / 上级 (delegate parent) / 子任务 (children).
  const upstream = run.dependsOn
    .map((id) => runs.find((r) => r.id === id))
    .filter((r): r is ProjectedRun => r != null);
  const downstream = runs.filter((r) => r.dependsOn.includes(run.id));
  const parent =
    run.parentRunId != null && run.continuesRunId == null
      ? (runs.find((r) => r.id === run.parentRunId) ?? null)
      : null;
  const children = runs.filter(
    (r) => r.parentRunId === run.id && r.continuesRunId == null,
  );
  const roleOf = (r: ProjectedRun): string =>
    r.role ?? agents.find((a) => a.id === r.agentId)?.role ?? r.agentId;

  const hasResources = !!(run.usage || run.cost || run.model);
  const hasRelations =
    upstream.length > 0 ||
    downstream.length > 0 ||
    parent != null ||
    children.length > 0;

  return (
    <Modal
      className="run-detail"
      onClose={onClose}
      label={`${name} · 队员详情`}
    >
      <header className="rd-head">
        <span className="rd-title">{name}</span>
        <span className={`run-badge badge-${st.tone}`}>{st.label}</span>
        {run.durationMs != null && (
          <span className="rd-dur">{formatDuration(run.durationMs)}</span>
        )}
        <button
          type="button"
          className="rd-close"
          onClick={onClose}
          aria-label="关闭"
        >
          ✕
        </button>
      </header>
      <div className="rd-body">
        <RunPills
          run={run}
          isChild={isChild}
          continuationIndex={continuationIndexOf(runs, run)}
        />

        <RunSection title={roundFocus != null ? "本轮焦点" : "任务"}>
          <Markdown content={roundFocus ?? run.task} evidence />
        </RunSection>

        {chain && (
          <RunSection title={isDebateChain ? "轮次" : "接续"}>
            <div className="rd-chain">
              {chain.map(({ version, run: v }) => {
                const current = v.id === run.id;
                const label = isDebateChain
                  ? `第 ${v.round || version} 轮`
                  : version === 1
                    ? "现场"
                    : `续 ×${version - 1}`;
                return (
                  <button
                    key={v.id}
                    type="button"
                    className={`rd-chip${current ? " rd-chip-current" : ""}`}
                    disabled={current}
                    onClick={() => onSelect(v.id)}
                  >
                    {label}
                    {current ? " · 当前" : ""}
                  </button>
                );
              })}
            </div>
          </RunSection>
        )}

        {run.escalations.length > 0 && (
          <RunSection title={`向上升级 (${run.escalations.length})`}>
            <div className="rd-stack">
              {run.escalations.map((esc, i) => {
                const detail = escalationDetail(esc);
                return (
                  <div
                    // biome-ignore lint/suspicious/noArrayIndexKey: per-run escalations are append-only with stable order
                    key={i}
                    className="run-escalation"
                  >
                    <span className="run-escalation-q">
                      ↑ {esc.question}
                      {esc.blocking ? " · 阻断性" : ""}
                    </span>
                    {detail && (
                      <span className="run-escalation-a">{detail}</span>
                    )}
                  </div>
                );
              })}
            </div>
          </RunSection>
        )}

        {contextBlocks.length > 0 && (
          <RunSection title={`收到的上下文 · ${contextBlocks.length} 段`}>
            <div className="recv-list">
              {contextBlocks.map((b, i) => (
                <ContextBlockRow key={`${b.channel}-${i}`} block={b} />
              ))}
            </div>
          </RunSection>
        )}

        {reasoning && (
          <RunSection title="思考">
            <pre className="rd-reasoning">{reasoning}</pre>
          </RunSection>
        )}

        {run.error && (
          <RunSection title="错误">
            <p className="run-error">{run.error}</p>
          </RunSection>
        )}

        {toolCalls.length > 0 && (
          <RunSection title={`工具明细 (${toolCalls.length})`}>
            <div className="rd-tools">
              {toolCalls.map((c) => (
                <RunToolRow key={c.id} call={c} />
              ))}
            </div>
          </RunSection>
        )}

        {output && (
          <RunSection title="输出">
            <div className="rd-output">
              <Markdown content={output} evidence />
            </div>
          </RunSection>
        )}

        {run.debrief ? (
          <DebriefBlock debrief={run.debrief} />
        ) : run.outputSummary ? (
          <RunSection title="结论">
            <Markdown content={run.outputSummary} evidence />
          </RunSection>
        ) : null}

        {hasResources && <ResourceBlock run={run} agent={agent} />}

        {hasRelations && (
          <RunSection title="关系">
            <div className="rd-stack">
              {upstream.length > 0 && (
                <RunRefGroup
                  label="依赖"
                  runs={upstream}
                  roleOf={roleOf}
                  onSelect={onSelect}
                />
              )}
              {downstream.length > 0 && (
                <RunRefGroup
                  label="后续"
                  runs={downstream}
                  roleOf={roleOf}
                  onSelect={onSelect}
                />
              )}
              {parent && (
                <RunRefGroup
                  label="上级"
                  runs={[parent]}
                  roleOf={roleOf}
                  onSelect={onSelect}
                />
              )}
              {children.length > 0 && (
                <RunRefGroup
                  label={`子任务 (${children.length})`}
                  runs={children}
                  roleOf={roleOf}
                  onSelect={onSelect}
                />
              )}
            </div>
          </RunSection>
        )}
      </div>
    </Modal>
  );
}

/** A titled run-detail section (label + body), the mobile mirror of the desktop detail `Section`. */
function RunSection({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rd-section">
      <h4 className="rd-section-title">{title}</h4>
      {children}
    </section>
  );
}

/** One label→value row in the 资源 metrics block. */
function MetricRow({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <div className="rd-metric">
      <span className="rd-metric-label">{label}</span>
      <span className={`rd-metric-value${mono ? " rd-mono" : ""}`}>
        {value}
      </span>
    </div>
  );
}

/** A labelled list of related runs (依赖 / 后续 / 上级 / 子任务) — each row navigates the panel to
 *  that run (关系跳转), reusing the same status tone dot as the cards. */
function RunRefGroup({
  label,
  runs,
  roleOf,
  onSelect,
}: {
  label: string;
  runs: ProjectedRun[];
  roleOf: (r: ProjectedRun) => string;
  onSelect: (runId: string) => void;
}) {
  return (
    <div className="rd-refs">
      <div className="rd-refs-label">{label}</div>
      {runs.map((r) => {
        const st = runStatusLabel(r.status, r);
        return (
          <button
            key={r.id}
            type="button"
            className="rd-ref"
            onClick={() => onSelect(r.id)}
          >
            <span className={`rd-ref-dot dot-${st.tone}`} />
            <span className="rd-ref-name">{roleOf(r)}</span>
            {r.task && <span className="rd-ref-task">{r.task}</span>}
          </button>
        );
      })}
    </div>
  );
}

/** One worker tool call (RunDetail · 工具明细) — reuses the CEO-side ToolStep visual language
 *  (.tool*): 中文名 + 参数 detail + status, click to expand the raw args / result pre block. The
 *  rich 6-类 tool rendering (desktop) is intentionally NOT ported (架构决策③). */
function RunToolRow({ call }: { call: RunToolCall }) {
  const [open, setOpen] = useState(false);
  const args = Object.keys(call.arguments).length > 0 ? call.arguments : null;
  const detail = toolDetail(call.arguments);
  const ceilingGuidance =
    call.status === "error" &&
    isFileReadCeilingGuidance(call.toolName, call.result);
  const status =
    call.status === "running"
      ? "Running"
      : ceilingGuidance
        ? "Notice"
        : call.status === "error"
          ? "Failed"
          : "Done";
  const hasBody = !!args || (call.result != null && call.result !== "");
  const shellClass = ceilingGuidance
    ? "tool tool-guidance"
    : `tool tool-${call.status}`;
  return (
    <div className={shellClass}>
      <button
        type="button"
        className="tool-head"
        onClick={() => setOpen((o) => !o)}
      >
        <span className="tool-name">
          {toolLabel(call.toolName)}
          {detail && <span className="tool-detail">{detail}</span>}
        </span>
        <span className="tool-status">{status}</span>
      </button>
      {open && hasBody && (
        <div className="tool-body">
          {args && (
            <pre className="tool-pre">{JSON.stringify(args, null, 2)}</pre>
          )}
          {call.result != null && call.result !== "" && (
            <pre className="tool-pre">{call.result}</pre>
          )}
        </div>
      )}
    </div>
  );
}

/** One 收到的上下文 block (RunDetail) — reuses the CEO-side ReceivedContext visual language
 *  (.recv*): channel origin + heading, then the body the worker read + any files / 已截断 mark. */
function ContextBlockRow({ block }: { block: ContextBlockWire }) {
  return (
    <div className="recv-item">
      <div className="recv-head">
        <span className="recv-channel">
          {CONTEXT_CHANNEL_LABEL[block.channel] ?? block.channel}
        </span>
        {block.heading && <span className="recv-heading">{block.heading}</span>}
      </div>
      {block.body && <pre className="recv-body">{block.body}</pre>}
      {block.files.length > 0 && (
        <div className="recv-files">
          {block.files.map((f) => (
            <span key={f} className="recv-file">
              {f}
            </span>
          ))}
        </div>
      )}
      {block.truncated && (
        <div className="recv-trunc">已截断（完整内容已传给 AI）</div>
      )}
    </div>
  );
}

/** 完工交接简报 (run_completed.debrief) — the worker's OWN structured wrap-up (结论 / 关键要点 /
 *  关键假设 / 建议下一步); renders only the sections it authored. */
function DebriefBlock({ debrief }: { debrief: RunDebrief }) {
  const { summary, key_points, assumptions, next_steps } = debrief;
  return (
    <RunSection title="交接简报">
      <div className="rd-debrief">
        {summary && (
          <div className="rd-debrief-part">
            <div className="rd-part-label">结论</div>
            <Markdown content={summary} evidence />
          </div>
        )}
        {key_points && key_points.length > 0 && (
          <div className="rd-debrief-part">
            <div className="rd-part-label">关键要点</div>
            <ul className="rd-points">
              {key_points.map((pt, i) => (
                <li key={`${i}:${pt}`}>{pt}</li>
              ))}
            </ul>
          </div>
        )}
        {assumptions && (
          <div className="rd-debrief-part">
            <div className="rd-part-label">关键假设</div>
            <p className="rd-assume">{assumptions}</p>
          </div>
        )}
        {next_steps && (
          <div className="rd-debrief-part">
            <div className="rd-part-label">建议下一步</div>
            <Markdown content={next_steps} evidence />
          </div>
        )}
      </div>
    </RunSection>
  );
}

/** 资源用量 (RunDetail) — 档位 / 思考 (from the agent) + 模型 / 成本 / token (from the run's
 *  run_completed usage+cost). All-zero cost shows「—」. */
function ResourceBlock({
  run,
  agent,
}: {
  run: ProjectedRun;
  agent: ProjectedAgent | undefined;
}) {
  const { usage, cost, model } = run;
  const money =
    cost && cost.total > 0
      ? { nano: cost.total, estimated: false }
      : cost?.estimated_total && cost.estimated_total > 0
        ? { nano: cost.estimated_total, estimated: true }
        : null;
  const tokenTotal = usage ? usage.input + usage.output : 0;
  const byokUnpriced = cost?.pricing_source === "unpriced";
  // 未计价 ≠ 估算：社区价目未命中时连估算值都没有，标注要如实（与桌面同口径）。
  const byokLabel =
    cost?.pricing_source === "unpriced" ? "自带密钥·未计价" : "自带密钥·估算";
  const cacheRate =
    usage && usage.input > 0
      ? Math.round((usage.cache_hit / usage.input) * 100)
      : 0;
  return (
    <RunSection title="资源">
      <div className="rd-metrics">
        {agent && (
          <MetricRow label="思考" value={reasoningLabel(agent.thinking)} />
        )}
        {model && <MetricRow label="模型" value={model} mono />}
        {money && money.nano > 0 && (
          <MetricRow
            label={money.estimated ? "成本（自带密钥·估算）" : "成本"}
            value={formatCostYuan(money.nano, money.estimated)}
          />
        )}
        {!money && usage && tokenTotal > 0 && byokUnpriced && (
          <MetricRow
            label={byokLabel}
            value={`${formatCompact(usage.input)}↑ / ${formatCompact(usage.output)}↓`}
          />
        )}
        {usage && (
          <>
            <MetricRow label="输入 token" value={formatCompact(usage.input)} />
            <MetricRow
              label="缓存命中"
              value={`${formatCompact(usage.cache_hit)} · ${cacheRate}%`}
            />
            <MetricRow label="输出 token" value={formatCompact(usage.output)} />
            <MetricRow
              label="推理 token"
              value={formatCompact(usage.reasoning)}
            />
          </>
        )}
      </div>
    </RunSection>
  );
}
