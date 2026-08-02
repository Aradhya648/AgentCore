/**
 * Collaboration-graph Live layer — derived selectors over `execution@playhead`.
 *
 * No writable GraphLive table: faces / edges subscribe to the projected Execution
 * (or Inject paint context) by id. Document shells stay referentially stable while
 * streaming deltas only re-render the subscribed face.
 */

import {
  challengePreviewFromContext,
  debateFacePrimaryFromContext,
} from "@/components/chat/debate/debateFaceCopy";
import { captainSynthesisPreviewText } from "@/components/chat/teamSynthesisPhase";
import { useCoordinationWaitChrome } from "@/components/chat/useCoordinationWaitChrome";
import type { InjectGraphOverlay } from "@/lib/causalInject";
import {
  estimateTokens,
  formatCostCaption,
  headText,
  pickCostMoney,
  tailText,
} from "@/lib/format";
import { detectReviewConcern } from "@/lib/reviewConcern";
import {
  type Execution,
  type RunNode,
  type RunStatus,
  debateBeatFromContext,
  useActiveExecField,
  useProjectedExecution,
} from "@/stores/execution";
import { createContext, useContext, useMemo } from "react";
import type { ActSummaryData } from "./ActSummaryNode";
import {
  type AgentNodeData,
  isDebateAgentNode,
  pickEscalationKind,
  revisionFeedbackSummary,
} from "./agentNode/shared";
import { INPUT_ID } from "./constants";
import { useGraphActions } from "./graphActions";
import {
  aggregateDebateRoundStatus,
  debateRoundActiveBeat,
  debateRoundPhaseLabel,
  debateRoundSettledMark,
  deriveArtifacts,
  deriveCaptainStatus,
  pickDebateCrossExamActivateId,
} from "./helpers";
import { stripNamespace } from "./ids";
import { type GraphScene, buildGraphScene } from "./scene";

/** When true, node/edge faces self-read Live; Document shells omit live fields. */
export const GraphDocumentModeContext = createContext(false);

export function useGraphDocumentMode(): boolean {
  return useContext(GraphDocumentModeContext);
}

/** Inject highlight / dim paint — Live overlay; never baked into Document edges. */
export type GraphInjectPaint = {
  highlightEdgeIds: ReadonlySet<string>;
  focusedEdgeIds: ReadonlySet<string>;
  dimUnrelatedEdges: boolean;
} | null;

export const GraphInjectPaintContext = createContext<GraphInjectPaint>(null);

export function useGraphInjectPaint(): GraphInjectPaint {
  return useContext(GraphInjectPaintContext);
}

/** Final-answer text for captain preview (drill-in); not on Document shells. */
export const GraphCaptainAnswerContext = createContext<{
  content: string;
} | null>(null);

/** Scene topology for Live face derivation (same lifetime as Document). */
export const GraphSceneContext = createContext<GraphScene | null>(null);

export function useGraphScene(): GraphScene | null {
  return useContext(GraphSceneContext);
}

function sumDurationMs(
  runs: readonly { durationMs?: number | null }[],
): number | null {
  let sum = 0;
  let any = false;
  for (const r of runs) {
    if (r.durationMs != null && r.durationMs > 0) {
      sum += r.durationMs;
      any = true;
    }
  }
  return any ? sum : null;
}

/**
 * Live face fields for one agent (or debate-round host) run.
 * Pure over Execution + scene beat folds — safe for hooks / tests.
 */
export function deriveAgentNodeLive(
  execution: Execution,
  run: RunNode,
  opts: {
    scene: GraphScene | null;
    litRunId: string | null;
    enterIndex: number;
    unitExpanded: boolean;
    nodeWidth?: number;
    handleDirection?: "vertical" | "horizontal";
    activateNode?: (id: string) => void;
    toggleUnitExpand?: (unitId: string) => void;
  },
): AgentNodeData {
  const captainId = execution.runs.find((r) => r.kind === "captain")?.id;
  const workerIdSet = new Set(
    execution.runs.filter((r) => r.id !== captainId).map((r) => r.id),
  );
  const runById = new Map(execution.runs.map((r) => [r.id, r]));
  const foldInfo = opts.scene?.fold;
  const foldedCx = (opts.scene?.beatFoldsByHost.get(run.id) ?? [])
    .map((id) => runById.get(id))
    .filter((r): r is RunNode => r != null);
  const roundRuns = foldedCx.length > 0 ? [run, ...foldedCx] : [run];
  const aggregatedStatus: RunStatus =
    foldedCx.length > 0
      ? aggregateDebateRoundStatus(roundRuns.map((r) => r.status))
      : run.status;
  const activeBeat =
    foldedCx.length > 0
      ? debateRoundActiveBeat(
          run.status,
          foldedCx.map((r) => r.status),
        )
      : "statement";
  const phaseLabel = debateRoundPhaseLabel(
    aggregatedStatus,
    activeBeat,
    foldedCx.length > 0,
  );
  const faceRun =
    activeBeat === "cross_exam"
      ? (foldedCx.find((r) => r.status === "running") ??
        foldedCx[foldedCx.length - 1] ??
        run)
      : run;
  const agent = execution.agents.find((a) => a.id === faceRun.agentId);
  const hostAgent = execution.agents.find((a) => a.id === run.agentId);
  const output = agent ? agent.outputChunks.join("") : "";
  const reasoning = agent ? agent.reasoningChunks.join("") : "";
  const reviewConcern =
    output.length >= 12
      ? detectReviewConcern(output, {
          role: agent?.role ?? faceRun.role,
          runId: faceRun.id,
        })
      : null;
  const focused =
    opts.litRunId === run.id || foldedCx.some((r) => r.id === opts.litRunId);
  const isContinuation = run.continuesRunId != null;
  const isSubtask =
    !isContinuation &&
    !!run.parentRunId &&
    run.parentRunId !== run.id &&
    workerIdSet.has(run.parentRunId);
  const foldedChildCount = foldInfo?.descendants.get(run.id)?.length ?? 0;
  const durationMs =
    foldedCx.length > 0 ? sumDurationMs(roundRuns) : run.durationMs;
  let costNano = 0;
  let costEstimated = false;
  for (const r of roundRuns) {
    const m = pickCostMoney(r.cost);
    if (!m || m.nano <= 0) continue;
    costNano += m.nano;
    if (m.estimated) costEstimated = true;
  }
  const realTokens = roundRuns.reduce(
    (n, r) => n + (r.usage ? r.usage.input + r.usage.output : 0),
    0,
  );
  const activateId =
    aggregatedStatus === "running" && faceRun.id !== run.id
      ? faceRun.id
      : run.id;
  const cxActivateId =
    foldedCx.length > 0 ? pickDebateCrossExamActivateId(foldedCx) : null;
  const settledMark =
    foldedCx.length > 0
      ? debateRoundSettledMark(
          aggregatedStatus,
          true,
          foldedCx.map((r) => r.status),
          foldedCx.map((r) => debateBeatFromContext(r.receivedContext)),
        )
      : null;
  const activate = opts.activateNode;
  const toggle = opts.toggleUnitExpand;

  return {
    agentId: run.agentId,
    role: (hostAgent ?? agent)?.role ?? run.agentId,
    runId: run.id,
    status: aggregatedStatus,
    isAnimating: aggregatedStatus === "running",
    task: run.task,
    error:
      aggregatedStatus === "failed"
        ? (roundRuns.find((r) => r.status === "failed")?.error ?? run.error)
        : run.error,
    failureKind:
      aggregatedStatus === "failed"
        ? (roundRuns.find((r) => r.status === "failed")?.failureKind ??
          run.failureKind)
        : run.failureKind,
    productLanded:
      aggregatedStatus === "failed"
        ? (roundRuns.find((r) => r.status === "failed")?.productLanded ??
          run.productLanded)
        : run.productLanded,
    outputPreview: tailText(output),
    debateFacePrimary: isDebateAgentNode({
      stance: run.stance,
      group: run.group,
    })
      ? debateFacePrimaryFromContext(run.receivedContext)
      : null,
    challengePreview: isDebateAgentNode({
      stance: run.stance,
      group: run.group,
    })
      ? challengePreviewFromContext(run.receivedContext)
      : null,
    reasoningPreview: tailText(reasoning),
    toolProgress: agent?.toolProgress ?? null,
    toolExecutionLive: agent?.toolExecutionLive ?? null,
    phase: faceRun.phase ?? run.phase ?? null,
    phaseTool: faceRun.phaseTool ?? run.phaseTool ?? null,
    tokenCount: estimateTokens(output),
    toolCount: agent?.toolCalls.length ?? 0,
    artifacts: agent ? deriveArtifacts(agent.toolCalls) : [],
    focused,
    nodeWidth: opts.nodeWidth,
    model: faceRun.model ?? run.model,
    durationMs,
    startedAt: faceRun.startedAt ?? run.startedAt,
    realTokens,
    costText:
      costNano > 0 ? formatCostCaption(costNano, costEstimated) : undefined,
    handleDirection: opts.handleDirection,
    isSubtask,
    isRevision: isContinuation,
    continuationIndex: run.continuationIndex,
    continuesRunId: run.continuesRunId,
    round: run.round,
    debateBeat: isContinuation
      ? debateBeatFromContext(run.receivedContext)
      : null,
    debateRoundPhase: phaseLabel,
    debateCrossExamMark: settledMark,
    onActivateCrossExam:
      settledMark && cxActivateId && activate
        ? () => activate(cxActivateId)
        : undefined,
    group: run.group,
    revisionSummary: isContinuation
      ? revisionFeedbackSummary(run.receivedContext)
      : null,
    revised: run.revised,
    replacesRunId: run.replacesRunId,
    didRework: (hostAgent ?? agent)?.didRework === true,
    stance: run.stance,
    checkpoint: run.checkpoint,
    escalationPending: roundRuns.reduce(
      (n, r) => n + r.escalations.filter((e) => e.status === "pending").length,
      0,
    ),
    escalationRaised: roundRuns.reduce(
      (n, r) => n + r.escalations.filter((e) => e.status === "raised").length,
      0,
    ),
    escalationKind: pickEscalationKind(roundRuns.flatMap((r) => r.escalations)),
    reviewConcern,
    foldedChildCount:
      foldedChildCount > 0 && !foldInfo?.debateUnits.has(run.id)
        ? foldedChildCount
        : undefined,
    unitExpanded: opts.unitExpanded,
    onToggleUnitExpand: toggle ? () => toggle(run.id) : undefined,
    enterIndex: opts.enterIndex,
    onActivate: activate ? () => activate(activateId) : undefined,
  };
}

/** Document shell whitelist for agent nodes (identity / direction only). */
export type AgentNodeShell = {
  agentId: string;
  role: string;
  runId: string;
  task: string;
  handleDirection?: "vertical" | "horizontal";
  isSubtask?: boolean;
  isRevision?: boolean;
  continuationIndex?: number;
  continuesRunId?: string | null;
  round?: number;
  group?: string | null;
  stance?: AgentNodeData["stance"];
  replacesRunId?: string | null;
  revised?: AgentNodeData["revised"];
  enterIndex?: number;
  nodeWidth?: number;
  unitExpanded?: boolean;
  foldedChildCount?: number;
  debateBeat?: AgentNodeData["debateBeat"];
};

export function agentNodeToShell(d: AgentNodeData): AgentNodeShell {
  return {
    agentId: d.agentId,
    role: d.role,
    runId: d.runId,
    task: d.task,
    handleDirection: d.handleDirection,
    isSubtask: d.isSubtask,
    isRevision: d.isRevision,
    continuationIndex: d.continuationIndex,
    continuesRunId: d.continuesRunId,
    round: d.round,
    group: d.group,
    stance: d.stance,
    replacesRunId: d.replacesRunId,
    revised: d.revised,
    enterIndex: d.enterIndex,
    nodeWidth: d.nodeWidth,
    unitExpanded: d.unitExpanded,
    foldedChildCount: d.foldedChildCount,
    debateBeat: d.debateBeat,
  };
}

function pendingShell(shell: AgentNodeShell): AgentNodeData {
  return {
    ...shell,
    status: "pending",
    isAnimating: false,
    outputPreview: "",
    tokenCount: 0,
    toolCount: 0,
    focused: false,
  } as AgentNodeData;
}

/**
 * Subscribe to Live face for an agent Document shell.
 * Returns full AgentNodeData merged from shell identity + execution@playhead.
 */
export function useAgentNodeLive(shell: AgentNodeShell): AgentNodeData {
  const execution = useProjectedExecution();
  const actions = useGraphActions();
  const scene = useGraphScene();
  return useMemo(() => {
    if (!execution) return pendingShell(shell);
    const run = execution.runs.find((r) => r.id === shell.runId);
    if (!run) return pendingShell(shell);
    return deriveAgentNodeLive(execution, run, {
      scene,
      litRunId: actions.litRunId,
      enterIndex: shell.enterIndex ?? 0,
      unitExpanded: shell.unitExpanded ?? false,
      nodeWidth: shell.nodeWidth,
      handleDirection: shell.handleDirection,
      activateNode: actions.activateNode,
      toggleUnitExpand: actions.toggleUnitExpand,
    });
  }, [execution, shell, scene, actions]);
}

export type EndpointLive = {
  status: RunStatus;
  preview?: string;
  statusCaption?: string;
  focused: boolean;
  label: string;
  onActivate?: () => void;
};

export function useInputEndpointLive(labelFromShell: string): EndpointLive {
  const execution = useProjectedExecution();
  const actions = useGraphActions();
  return useMemo(() => {
    const label = labelFromShell || execution?.taskSummary || "";
    return {
      status: "completed" as RunStatus,
      label,
      focused:
        !!actions.taskMessageId &&
        actions.litEndpointMessageId === actions.taskMessageId,
      onActivate: actions.taskMessageId
        ? () => actions.activateNode(INPUT_ID)
        : undefined,
    };
  }, [labelFromShell, execution, actions]);
}

export function useCaptainEndpointLive(runId: string): EndpointLive {
  const execution = useProjectedExecution();
  const actions = useGraphActions();
  const answer = useContext(GraphCaptainAnswerContext);
  const teamSynthesisPreview = useActiveExecField(
    (rt) => rt.teamSynthesisPreview,
  );
  const { captainCaption: captainWaitCaption } =
    useCoordinationWaitChrome(execution);

  return useMemo(() => {
    const captainStatus = execution
      ? deriveCaptainStatus(execution, runId, {
          turnTerminal: actions.turnTerminal,
        })
      : ("pending" as RunStatus);
    const waitCaption = (captainWaitCaption ?? "").trim();
    const sinkStatus: RunStatus = waitCaption ? "running" : captainStatus;
    const answerPreview = answer?.content ? headText(answer.content) : "";
    const synthPreview =
      !answerPreview && sinkStatus === "running" && !waitCaption
        ? captainSynthesisPreviewText(teamSynthesisPreview)
        : "";
    return {
      status: sinkStatus,
      statusCaption: waitCaption || undefined,
      label: "",
      preview: answerPreview || synthPreview,
      focused:
        !!actions.finalAnswerId &&
        actions.litEndpointMessageId === actions.finalAnswerId,
      onActivate: actions.finalAnswerId
        ? () => actions.activateNode(runId)
        : undefined,
    };
  }, [
    execution,
    runId,
    actions,
    answer,
    teamSynthesisPreview,
    captainWaitCaption,
  ]);
}

export type ActSummaryLive = Pick<
  ActSummaryData,
  | "status"
  | "roles"
  | "agentCount"
  | "completed"
  | "total"
  | "durationMs"
  | "pendingDecisions"
  | "recoverable"
>;

/** Live act-card progress — derived from current Execution via scene IR. */
export function useActSummaryLive(actId: string): ActSummaryLive | null {
  const execution = useProjectedExecution();
  return useMemo(() => {
    if (!execution) return null;
    const scene = buildGraphScene(execution, { inputId: INPUT_ID });
    const sa = scene.acts.find((a) => a.actId === actId);
    if (!sa) return null;
    return {
      status: sa.status,
      roles: sa.roles,
      agentCount: sa.agentCount,
      completed: sa.completed,
      total: sa.total,
      durationMs: sa.durationMs,
      pendingDecisions: sa.pendingDecisions,
      recoverable: sa.recoverable,
    };
  }, [execution, actId]);
}

/** Edge animated? — Live read of target run / captain status. */
export function useStepEdgeAnimated(
  targetId: string,
  captainRunId: string | null,
): boolean {
  const documentMode = useGraphDocumentMode();
  const execution = useProjectedExecution();
  const { turnTerminal } = useGraphActions();
  // Canvas namespaces RF edge endpoints as `turnId::bare`; Live looks up bare run ids.
  const bareTarget = stripNamespace(targetId);
  return useMemo(() => {
    if (!documentMode || !execution) return false;
    if (captainRunId && bareTarget === captainRunId) {
      return (
        deriveCaptainStatus(execution, captainRunId, { turnTerminal }) ===
        "running"
      );
    }
    return (
      execution.runs.find((s) => s.id === bareTarget)?.status === "running"
    );
  }, [documentMode, execution, bareTarget, captainRunId, turnTerminal]);
}

export function injectPaintFromOverlay(
  overlay: InjectGraphOverlay | null | undefined,
): GraphInjectPaint {
  if (!overlay) return null;
  return {
    highlightEdgeIds: overlay.highlightEdgeIds,
    focusedEdgeIds: overlay.focusedEdgeIds,
    dimUnrelatedEdges: overlay.dimUnrelatedEdges ?? false,
  };
}

/** Captain run id for StepEdge Live animated (pane-level, stable). */
export const GraphCaptainRunIdContext = createContext<string | null>(null);
