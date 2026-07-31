import { DebateProgressLine } from "@/components/chat/DebateProgressLine";
import { StatusStrip } from "@/components/chat/StatusStrip";
import { TeamNotesPanel } from "@/components/chat/TeamNotesPanel";
import { UserInterjectionsPanel } from "@/components/chat/UserInterjectionsPanel";
import {
  shouldHostPreviewInGraph,
  teamHasStartedRuns,
} from "@/components/chat/debatePreviewPlacement";
import { teamNotesDefaultExpanded } from "@/components/chat/teamNotesDefaults";
import { GraphView } from "@/components/graph/GraphView";
import { executionGraphCapabilities } from "@/components/graph/planCapabilities";
import { ContextualTip } from "@/components/onboarding/ContextualTip";
import { formatCollabSummary } from "@/lib/collabSummary";
import {
  EMBED_DEFAULT_COL_WIDTH,
  estimateBbox,
  fitWidthBox,
  workerGraphShape,
} from "@/lib/elk-layout";
import { useConversationStore } from "@/stores/conversation";
import { useStreamAwareDisclosure } from "@/stores/disclosure";
import {
  type Execution,
  type ExecutionJournal,
  ExecutionScopeContext,
  type UserInterjection,
  isDebate,
  useExecutionStore,
  useMessageExecution,
} from "@/stores/execution";
import { useGraphStore } from "@/stores/graph";
import { useMessageInteractionCards } from "@/stores/interactions";
import { useSidePanelStore } from "@/stores/sidePanel";
import { turnDetailPath } from "@/stores/ui";
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";

/** Re-export gate used by fixture tests and graph consumers. */
export { teamHasStartedRuns } from "@/components/chat/debatePreviewPlacement";

const EMPTY_INTERJECTIONS: readonly UserInterjection[] = [];

/**
 * The multi-agent turn's primary surface, embedded in the assistant message
 * at the `team` marker slot (below the CEO lead-in content step): a compact
 * status strip (lifecycle + cost) over the live collaboration graph.
 *
 * Per-message (§9.3): keyed by the assistant message id, so live and reloaded
 * (historical) multi-agent turns render identically — the live turn streams into
 * the slot, a reloaded turn hydrates it from the persisted journal (`runs`), and
 * both project through the same fold. Node clicks drill into the passive
 * right-side panel; 「在画布打开」/「回放」navigate to the turn's full-screen
 * detail page (`#/conversations/:id/turn/:turnId`).
 */
export function InlineTeamGraph({
  messageId,
  executionId,
  journal,
}: {
  messageId: string;
  executionId: string;
  journal?: ExecutionJournal;
}) {
  const navigate = useNavigate();
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const hydrateFromJournal = useExecutionStore((s) => s.hydrateFromJournal);
  useEffect(() => {
    if (journal) hydrateFromJournal(messageId, journal);
  }, [journal, messageId, hydrateFromJournal]);

  const execution = useMessageExecution(messageId);
  // 「打开辩论室」/「在画布打开」/「回放」→ 全屏回合详情；辩论回合传 view=debate
  //（与右坞 RunDetailBody / RunModeratorLedger 深链一致）。
  const openInCanvas = useCallback(
    (autoplay: boolean) => {
      if (!conversationId) return;
      const view =
        execution && isDebate(execution) ? ("debate" as const) : undefined;
      navigate(
        turnDetailPath(conversationId, messageId, view, undefined, {
          autoplay,
        }),
      );
    },
    [conversationId, messageId, navigate, execution],
  );
  // 「改了 N 版」信号 → 深链全屏页的「对比」视图。
  const openRevisionsInCanvas = useCallback(() => {
    if (!conversationId) return;
    navigate(turnDetailPath(conversationId, messageId, "compare"));
  }, [conversationId, messageId, navigate]);
  const userInterjections = useExecutionStore(
    (s) => s.byId[messageId]?.userInterjections ?? EMPTY_INTERJECTIONS,
  );
  const { teamPreviews } = useMessageInteractionCards(
    conversationId,
    messageId,
  );
  const resolvedPreview = useMemo(
    () => teamPreviews.find((p) => p.status === "resolved") ?? null,
    [teamPreviews],
  );
  const message = useConversationStore((s) => {
    const key = s.currentConversationId ?? "";
    return s.byId[key]?.messages.find(
      (m) => m.id === messageId || m.serverMessageId === messageId,
    );
  });
  const collabSummary = useMemo(
    () => formatCollabSummary(message?.collab),
    [message?.collab],
  );
  const [measured, setMeasured] = useState<{
    height: number;
    overflowing: boolean;
  } | null>(null);
  const onMeasure = useCallback(
    (m: { height: number; overflowing: boolean }) => setMeasured(m),
    [],
  );
  const layoutKind = useGraphStore((s) => s.layoutKind);
  const fallbackHeight = useMemo(() => {
    if (!execution) return 0;
    const est = estimateBbox(workerGraphShape(execution.runs), layoutKind);
    return fitWidthBox(est.width, est.height, EMBED_DEFAULT_COL_WIDTH).height;
  }, [execution, layoutKind]);

  const caps = executionGraphCapabilities(execution);
  // 进行中（含跨回合追加重开）自动展开；收场后尊重用户折叠偏好。
  const graphLive =
    execution?.status === "running" || execution?.status === "paused";
  const [expanded, , setExpanded] = useStreamAwareDisclosure(
    `${messageId}:inline-graph`,
    Boolean(graphLive),
    { liveDefault: true, settledDefault: caps.inlineDefaultExpanded },
  );

  // 便签墙：运行中默认展开、结束默认折叠；用户选择跨卸载/刷新保留。
  const notesLive = teamNotesDefaultExpanded(
    execution?.status,
    execution?.teamNotes ?? [],
  );
  const [notesExpanded, , setNotesExpanded] = useStreamAwareDisclosure(
    `${messageId}:team-notes`,
    notesLive,
  );

  if (
    !execution ||
    execution.id !== executionId ||
    !caps.showsTeamGraph ||
    !teamHasStartedRuns(execution.runs)
  ) {
    return null;
  }

  const graphHeight = measured?.height ?? fallbackHeight;
  const hostPreview = shouldHostPreviewInGraph(resolvedPreview, execution.runs);
  // 推进线（认知轨迹）位置随辩论状态分治：进行中留在标题下方，让用户不点开也能瞥当前轮焦点；
  // 收场后标题已给出结论，推进线降权下移到协作图之后，头部只留一条结论行（前端UX设计.md §三）。
  const debateLive =
    isDebate(execution) &&
    (execution.status === "running" || execution.status === "paused");
  const debateSettled = isDebate(execution) && !debateLive;

  return (
    <ExecutionScopeContext.Provider value={messageId}>
      <ContextualTip tipId="inline_team_graph" placement="top" active>
        <div className="animate-task-card-enter mb-3 overflow-hidden rounded-xl border border-border bg-card">
          {/* 辩论全过程 / 版本对比等「过程产物」不再内联聊天——它们归画布放大态（统一辩论室 /
              统一「对比」视图），聊天正文只在状态条留信号（辩论 pill /「改了 N 版」chip）+ 入口 CTA
              （前端UX设计.md §4.1/§4.2/§6.4）。 */}
          <StatusStrip
            execution={execution}
            expanded={expanded}
            onToggle={() => setExpanded(!expanded)}
            onMaximize={() => openInCanvas(false)}
            onReplay={() => openInCanvas(true)}
            onOpenRevisions={openRevisionsInCanvas}
            collabSummary={collabSummary}
            teamPreview={hostPreview ? resolvedPreview : null}
          />
          {debateLive && (
            <DebateProgressLine
              execution={execution}
              disclosureKey={`${messageId}:debate-progress`}
            />
          )}
          {expanded && (
            <GraphArea
              execution={execution}
              messageId={messageId}
              height={graphHeight}
              onMeasure={onMeasure}
            />
          )}
          {debateSettled && (
            <DebateProgressLine
              execution={execution}
              disclosureKey={`${messageId}:debate-progress`}
            />
          )}
          {/* 协调中用户插话：轻量徽标「已传达给团队」/「已排队」。 */}
          <div className="px-3 pb-1">
            <UserInterjectionsPanel items={userInterjections} />
          </div>
          {/* 团队便签墙 (§2.2 通): collapsible; stays available when the graph is folded.
              Empty turns render nothing. */}
          <TeamNotesPanel
            notes={execution.teamNotes}
            expanded={notesExpanded}
            onExpandedChange={setNotesExpanded}
          />
        </div>
      </ContextualTip>
    </ExecutionScopeContext.Provider>
  );
}

function GraphArea({
  execution,
  messageId,
  height,
  onMeasure,
}: {
  execution: Execution;
  messageId: string;
  height: number;
  onMeasure: (m: { height: number; overflowing: boolean }) => void;
}) {
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);

  const onNodeSelect = (runId: string) => {
    const run = execution.runs.find((r) => r.id === runId);
    const role = execution.agents.find((a) => a.id === run?.agentId)?.role;
    showRunDetail(messageId, runId, role);
  };

  return (
    <div
      className="w-full select-none border-t border-border"
      style={{ height }}
    >
      <GraphView
        interactive={false}
        fitMode="width"
        onNodeSelect={onNodeSelect}
        onMeasure={onMeasure}
      />
    </div>
  );
}
