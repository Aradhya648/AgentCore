import type {
  DebateNarrativeRound,
  DebatePretrialCompletedPayload,
  DebatePretrialOrdersPayload,
  DebatePretrialProgressPayload,
  DebatePretrialStartedPayload,
} from "@/types/events";
import type { DebatePretrialProjection } from "@agentcore/protocol-conformance";
import type { Execution, RunNode } from "./types";

/**
 * 辩论参与者 group 白名单（辩形态 / 证人席）。
 * 禁止 `startsWith("debate:")`——庭前取证员曾挂 `debate:investigators:*` + parent=主辩，
 * 会把主辩晋升独立 debateUnits → ELK「第 N 次委派」假分带。
 */
export const DEBATE_PARTICIPANT_GROUPS = new Set([
  "debate:debate",
  "debate:red_team",
  "debate:roundtable",
  "debate:witness",
]);

/** 多方无 stance 的辩手席（圆桌 / 红队）；证人席另渠，不进 liveRounds。 */
const DEBATE_LIVE_SIDE_GROUPS = new Set([
  "debate:red_team",
  "debate:roundtable",
]);

/** 收场前 liveForm 可读的形态标签（不含 witness）。 */
export const DEBATE_FORM_GROUPS = new Set([
  "debate:debate",
  "debate:red_team",
  "debate:roundtable",
]);

export function isDebateFormGroup(group: string | null | undefined): boolean {
  return group != null && DEBATE_FORM_GROUPS.has(group);
}

export function isDebateParticipantGroup(
  group: string | null | undefined,
): boolean {
  return group != null && DEBATE_PARTICIPANT_GROUPS.has(group);
}

/** stance 非空或显式辩形态 / 证人席 group。 */
export function isDebateTaggedRun(r: {
  stance?: string | null;
  group?: string | null;
}): boolean {
  return r.stance != null || isDebateParticipantGroup(r.group);
}

/** 庭前取证员：`pretrial:investigators:{side}`（离开 debate: 参与者命名空间）。 */
export function isPretrialInvestigatorGroup(
  group: string | null | undefined,
): boolean {
  return group?.startsWith("pretrial:investigators:") ?? false;
}

/** Fold one 逐轮叙事 update (`debate_round_started` → focus only, verdict null;
 * `debate_round` → full focus/summary/verdict/sides) into the accumulated list,
 * keyed by `round_no` (a later `debate_round` overwrites the earlier focus-only
 * entry — it carries focus too), kept ascending. Shared by the live store action and
 * the conformance fold so both ends累积 identically. */
export function upsertDebateRound(
  rounds: DebateNarrativeRound[],
  round: DebateNarrativeRound,
): DebateNarrativeRound[] {
  const idx = rounds.findIndex((r) => r.round_no === round.round_no);
  if (idx === -1) {
    return [...rounds, round].sort((a, b) => a.round_no - b.round_no);
  }
  const next = [...rounds];
  next[idx] = round;
  return next;
}

/** 庭前取证折叠态（与 oracle `DebatePretrialProjection` 同形）。 */
export type DebatePretrialState = DebatePretrialProjection;

function emptyRunningPretrial(
  p: DebatePretrialStartedPayload | DebatePretrialOrdersPayload,
): DebatePretrialState {
  return {
    status: "running",
    thorough: p.thorough !== false,
    skipReason: ("skip_reason" in p ? p.skip_reason : null) ?? null,
    sides: (p.sides ?? []).map((s) => ({ key: s.key, name: s.name })),
    orders: [],
    investigators: [],
    evidenceLedgerCount: 0,
    fallbackSelfSearch: false,
    evidenceReady: false,
  };
}

/**
 * 折叠 `debate_pretrial_*`（权威 = completed）。与后端 oracle / 手机 fold 同语义，
 * 供 live store · hydrate · conformanceFold 共用。
 */
export function foldDebatePretrial(
  current: DebatePretrialState | null,
  type:
    | "debate_pretrial_started"
    | "debate_pretrial_orders"
    | "debate_pretrial_progress"
    | "debate_pretrial_completed",
  payload: unknown,
): DebatePretrialState | null {
  if (type === "debate_pretrial_started") {
    const p = payload as DebatePretrialStartedPayload;
    return emptyRunningPretrial(p);
  }
  if (type === "debate_pretrial_orders") {
    const p = payload as DebatePretrialOrdersPayload;
    const base = current ?? emptyRunningPretrial(p);
    const next: DebatePretrialState = {
      ...base,
      thorough: p.thorough !== false,
      sides:
        (p.sides ?? []).length > 0
          ? (p.sides ?? []).map((s) => ({ key: s.key, name: s.name }))
          : base.sides,
      orders: (p.orders ?? []).map((o) => ({
        side_key: o.side_key,
        tasks: (o.tasks ?? []).map((t) => ({
          query: t.query,
          ...(t.purpose ? { purpose: t.purpose } : {}),
        })),
        source: o.source ?? "empty",
      })),
    };
    const perSide = p.investigator_count_per_side ?? 0;
    if (perSide > 0) next.investigatorCountPerSide = perSide;
    return next;
  }
  if (type === "debate_pretrial_progress") {
    // 与 oracle 一致：无 started 时 progress 不落态。
    if (!current) return null;
    const p = payload as DebatePretrialProgressPayload;
    return {
      ...current,
      evidenceLedgerCount:
        p.evidence_ledger_count ?? current.evidenceLedgerCount,
    };
  }
  // completed — authoritative replace
  const p = payload as DebatePretrialCompletedPayload;
  return {
    status: p.status || "done",
    thorough: p.thorough !== false,
    skipReason: p.skip_reason ?? null,
    sides: (p.sides ?? []).map((s) => ({ key: s.key, name: s.name })),
    orders: (p.orders ?? []).map((o) => ({
      side_key: o.side_key,
      tasks: (o.tasks ?? []).map((t) => ({
        query: t.query,
        ...(t.purpose ? { purpose: t.purpose } : {}),
      })),
      source: o.source ?? "empty",
    })),
    investigators: (p.investigators ?? []).map((inv) => ({
      side_key: inv.side_key,
      run_id: inv.run_id,
      parent_run_id: inv.parent_run_id,
      ok: Boolean(inv.ok),
      ...(inv.task_query ? { task_query: inv.task_query } : {}),
    })),
    evidenceLedgerCount: p.evidence_ledger_count ?? 0,
    fallbackSelfSearch: Boolean(p.fallback_self_search),
    evidenceReady: Boolean(p.evidence_ready),
  };
}

/**
 * 辩论 continue_run 的发言角色（阶段化 beat）：与 `run_context.channel` 对齐——
 * `cross_exam` / `closing` 已在 wire；陈词续轮无专属 channel，归 `statement`。
 * 协作图角标 / 侧栏轮次轨据此区分「第 N 轮」与「第 N 轮·质询」/「结辩」，避免同轮双列同文。
 */
export type DebateBeat =
  | "statement"
  | "cross_exam"
  | "witness_exam"
  | "closing"
  | "attack"
  | "defense"
  | "rebuttal"
  | "thread"
  | "crux";

/** 从 `run_context` blocks 读 beat（复用既有 channel，不新造 wire 字段）。 */
export function debateBeatFromContext(
  blocks: ReadonlyArray<{ channel: string }> | null | undefined,
): DebateBeat {
  if (!blocks?.length) return "statement";
  if (blocks.some((b) => b.channel === "closing")) return "closing";
  if (blocks.some((b) => b.channel === "witness_exam")) return "witness_exam";
  if (blocks.some((b) => b.channel === "cross_exam")) return "cross_exam";
  if (blocks.some((b) => b.channel === "attack")) return "attack";
  if (blocks.some((b) => b.channel === "defense")) return "defense";
  if (blocks.some((b) => b.channel === "rebuttal")) return "rebuttal";
  if (blocks.some((b) => b.channel === "crux")) return "crux";
  if (blocks.some((b) => b.channel === "thread")) return "thread";
  return "statement";
}

/**
 * 陈词 / 可见宿主 beat：计入发言格 / 正反分桶 / 多方直播行 / 协作图列。
 * 质询·复攻·crux 折进同轮宿主；结辩独立终章列（辩论室 ClosingBlocks）。
 * 桌面 renderer 内 beat 判定的单一源——图 helpers 与 arena 分桶都读这里。
 */
export function isDebateStatementBeat(
  blocks: ReadonlyArray<{ channel: string }> | null | undefined,
): boolean {
  // 正反立论 / 红队攻·回应 / 圆桌线程 = 可见宿主；复攻·crux·质询折进宿主。
  const beat = debateBeatFromContext(blocks);
  return (
    beat === "statement" ||
    beat === "attack" ||
    beat === "defense" ||
    beat === "thread"
  );
}

/** 协作图折进同轮宿主的 beat（不独立成列）。 */
export function isDebateFoldedBeat(
  blocks: ReadonlyArray<{ channel: string }> | null | undefined,
): boolean {
  const beat = debateBeatFromContext(blocks);
  return (
    beat === "cross_exam" ||
    beat === "witness_exam" ||
    beat === "rebuttal" ||
    beat === "crux"
  );
}

/**
 * 辩论续写节点可见文案：首轮陈词无角标（由调用方跳过）；续轮陈词「第 N 轮」；
 * 质询「第 N 轮·质询」；结辩「结辩」（不挂轮次，避免与末轮陈词撞文）。
 */
export function debateBeatLabel(opts: {
  round?: number;
  revision?: number;
  beat?: DebateBeat | null;
}): string {
  const beat = opts.beat ?? "statement";
  if (beat === "closing") return "结辩";
  const n = opts.round && opts.round > 0 ? opts.round : (opts.revision ?? 0);
  if (beat === "cross_exam") return `第 ${n} 轮·质询`;
  if (beat === "witness_exam") return `第 ${n} 轮·证人`;
  if (beat === "attack") return `第 ${n} 轮·攻击`;
  if (beat === "defense") return `第 ${n} 轮·回应`;
  if (beat === "rebuttal") return `第 ${n} 轮·复攻`;
  if (beat === "thread") return `第 ${n} 轮·线程`;
  if (beat === "crux") return `第 ${n} 轮·crux`;
  return `第 ${n} 轮`;
}

/**
 * Whether a turn is a 辩论/审查 (前端UX设计.md §四).
 *
 * This is the single client-side signal that differentiates a debate from an
 * ordinary parallel batch — the DAG shape and SSE are identical (守住「形状是数据
 * 不是模式」), so the strip title / node badge / graph 分列 / 放大态「交锋」页 all key
 * off it.
 */
export function isDebate(execution: Execution): boolean {
  // 收场产物是辩论的强信号（debate_result 必带）。进行中无产物时退回辩手 run 的标签：
  // 2 方正反带 stance；多方圆桌/红队/证人席靠显式 group 白名单（禁 debate:* 前缀——
  // 取证员等附属 run 不得把整场误判 / 击穿布局）。
  return (
    execution.debate != null || execution.runs.some((r) => isDebateTaggedRun(r))
  );
}

/**
 * The debate roster split by side (前端UX设计.md §四), in plan order. Empty lists
 * for a non-debate turn. Used by the strip title now and the「左右并排对比」next.
 */
export function debateSides(execution: Execution): {
  pro: RunNode[];
  con: RunNode[];
} {
  const speech = (r: RunNode) =>
    r.stance != null && isDebateStatementBeat(r.receivedContext);
  return {
    pro: execution.runs.filter((r) => speech(r) && r.stance === "pro"),
    con: execution.runs.filter((r) => speech(r) && r.stance === "con"),
  };
}

/** One round's 正/反 within a comparison group (真·多轮辩论, 前端UX设计.md §四).
 * `round` is the 1-based turn; 0 means the group carries no round tags (即单轮辩论). */
export interface DebateRound {
  round: number;
  pro: RunNode[];
  con: RunNode[];
}

/** One comparison group: its full 正/反 rosters plus the same runs re-bucketed by
 * `round` (升序). A single-round group yields one bucket at round 0. */
export interface DebateGroup {
  key: string;
  pro: RunNode[];
  con: RunNode[];
  rounds: DebateRound[];
}

/**
 * The debate split into comparison groups (前端UX设计.md §四), one per `group` tag
 * (an untagged stance falls into the default `""` group), in first-seen order.
 * Powers the「左右并排对比」card: a turn can hold several opposing pairs (multi-
 * dimension review), each rendered as its own 正方 vs 反方 row. Empty for非辩论.
 *
 * Each group also carries its `rounds` — the same runs re-bucketed by `round`
 * (真·多轮辩论) in ascending turn order. The card lays a multi-round group out 逐轮
 * and a single-round one (all round 0) as a flat 正/反 pair, both off this one
 * projection — no second source of truth.
 *
 * 只收 {@link isDebateStatementBeat} 陈词；质询/结辩 continue_run 虽继承 stance，
 * 另渠呈现（与协作图 beat 折叠同口径）。
 */
export function debateGroups(execution: Execution): DebateGroup[] {
  const groups: DebateGroup[] = [];
  for (const run of execution.runs) {
    if (run.stance == null) continue;
    // 质询/结辩 continue_run 继承 stance，不得混入发言格（与协作图 beat 折叠同口径）。
    if (!isDebateStatementBeat(run.receivedContext)) continue;
    const key = run.group ?? "";
    let group = groups.find((g) => g.key === key);
    if (!group) {
      group = { key, pro: [], con: [], rounds: [] };
      groups.push(group);
    }
    (run.stance === "pro" ? group.pro : group.con).push(run);
    let bucket = group.rounds.find((r) => r.round === run.round);
    if (!bucket) {
      bucket = { round: run.round, pro: [], con: [] };
      group.rounds.push(bucket);
    }
    (run.stance === "pro" ? bucket.pro : bucket.con).push(run);
  }
  for (const group of groups) {
    group.rounds.sort((a, b) => a.round - b.round);
  }
  return groups;
}

/** One round of a multi-side debate (圆桌 / 红队 / 3+方) in progress: the round number
 * + that round's debater run per side. Unlike {@link DebateGroup} (正/反 stance pairs),
 * multi-side rounds have no stance to pair, so each side's run just sits in the row. */
export interface DebateLiveRound {
  round: number;
  runs: RunNode[];
}

/**
 * Multi-side debate (圆桌 / 红队 / 3+方) reconstructed into rounds for the in-progress
 * inline view — the gap {@link debateGroups} leaves (it only pairs stance-tagged 2方
 * debates, so 圆桌/红队 showed nothing inline until 收场). Under the moderator +
 * continue_run redesign a debater's round 1 is a plan-declared node (group `debate:*`,
 * no stance) and every later round is a 续写 revision of it, so we walk each side's
 * revision chain and bucket by the revision's {@link RunNode.round} (乙 wire 携
 * round/stance · 单一轮次投影) — the SAME `round` field debateGroups reads.
 * renders via {@link RunNode}'s agent (the revision inherits the side's role + streams
 * its own output). Empty for 非辩论 / 2方正反 (handled by debateGroups) / 收场后.
 */
export function debateLiveRounds(execution: Execution): DebateLiveRound[] {
  const sides = execution.runs.filter(
    (r) =>
      r.group != null &&
      DEBATE_LIVE_SIDE_GROUPS.has(r.group) &&
      r.stance == null &&
      r.continuesRunId == null,
  );
  if (sides.length === 0) return [];
  const revisionsByOriginal = new Map<string, RunNode[]>();
  for (const run of execution.runs) {
    if (run.continuesRunId == null) continue;
    // 质询/结辩续写不进多方发言行（与 debateGroups / 协作图折叠同口径）。
    if (!isDebateStatementBeat(run.receivedContext)) continue;
    const list = revisionsByOriginal.get(run.continuesRunId) ?? [];
    list.push(run);
    revisionsByOriginal.set(run.continuesRunId, list);
  }
  // 单一轮次投影: round 只读 wire 字段（无 round 时为 0）。
  const roundOf = (r: RunNode): number => r.round ?? 0;
  let maxRound = 1;
  for (const side of sides) {
    for (const rev of revisionsByOriginal.get(side.id) ?? []) {
      maxRound = Math.max(maxRound, roundOf(rev));
    }
  }
  const rounds: DebateLiveRound[] = [];
  for (let r = 1; r <= maxRound; r++) {
    const runs: RunNode[] = [];
    for (const side of sides) {
      if (r === 1) {
        runs.push(side);
        continue;
      }
      const rev = (revisionsByOriginal.get(side.id) ?? []).find(
        (x) => roundOf(x) === r,
      );
      if (rev) runs.push(rev);
    }
    if (runs.length > 0) rounds.push({ round: r, runs });
  }
  return rounds;
}
