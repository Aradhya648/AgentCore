import { GraphAppendAnchor } from "@/components/chat/GraphAppendAnchor";
import { InlineTeamGraph } from "@/components/chat/InlineTeamGraph";
import { Markdown } from "@/components/chat/Markdown";
import {
  ComposingToolLine,
  ToolLine,
  ToolLineGroup,
} from "@/components/chat/ToolLine";
import {
  type TimelineNode,
  groupToolRuns,
  timelineNodeKeys,
} from "@/lib/processTimeline";
import type {
  CheckpointDisplay,
  NonBlockingAskDisplay,
  PlanReviewDisplay,
  TeamPreviewDisplay,
} from "@/stores/conversation";
import { useStreamAwareDisclosure } from "@/stores/disclosure";
import type { ExecutionJournal } from "@/stores/execution";
import { renderTimelineInteractionCard } from "@/stores/interactions/registryUi";
import type {
  Citation,
  ProcessStep,
  TurnEvidenceLedgerEntry,
} from "@/types/events";
import { ChevronDown, ChevronRight } from "lucide-react";
import { Fragment } from "react";
import { ThinkingDots, ThinkingHeader } from "./Thinking";

function isProcessNode(node: TimelineNode): boolean {
  return (
    node.kind === "reasoning" ||
    node.kind === "tool" ||
    node.kind === "tool-group"
  );
}

function countProcessStats(nodes: TimelineNode[]) {
  let reasoningCount = 0;
  let toolCount = 0;
  for (const node of nodes) {
    if (node.kind === "reasoning") reasoningCount++;
    else if (node.kind === "tool") toolCount++;
    else if (node.kind === "tool-group") toolCount += node.tools.length;
  }
  return { reasoningCount, toolCount };
}

function formatProcessSummary(
  reasoningCount: number,
  toolCount: number,
): string {
  const parts: string[] = [];
  if (reasoningCount > 0) {
    parts.push(
      `Thought ${reasoningCount} step${reasoningCount === 1 ? "" : "s"}`,
    );
  }
  if (toolCount > 0) {
    parts.push(`Used ${toolCount} tool${toolCount === 1 ? "" : "s"}`);
  }
  return parts.join(" · ");
}

function InlineReasoning({
  text,
  streaming,
  persistKey,
}: {
  text: string;
  streaming: boolean;
  /** 持久化键（`${messageId}:reason:${i}`）：给了才把「思考过程开合」跨卸载/刷新记住；缺省走会话态。 */
  persistKey?: string | null;
}) {
  // 「直播中自动展开、收场后按保存值」（Q3）——不再收场强制收起并遗忘。
  const [expanded, toggle] = useStreamAwareDisclosure(
    persistKey ?? null,
    streaming,
  );

  return (
    <div>
      <ThinkingHeader
        isStreaming={streaming}
        expanded={expanded}
        streamingLabel="Thinking…"
        doneLabel="Thought"
        onToggle={toggle}
      />
      {expanded && (
        <div className="mt-1.5 pl-3">
          <Markdown content={text} isStreaming={streaming} muted />
        </div>
      )}
    </div>
  );
}

function ProcessRow({
  step,
  streaming,
  citations,
  citationToDisplay,
  knownLedgerIds,
  evidenceLedger,
  turnKey,
  rowKey,
  conversationId,
}: {
  step: ProcessStep;
  streaming: boolean;
  citations: Citation[];
  citationToDisplay?: ReadonlyMap<number, number>;
  knownLedgerIds?: ReadonlySet<string> | null;
  evidenceLedger?: readonly TurnEvidenceLedgerEntry[] | null;
  /** 回合作用域（= messageId）：给了才持久化本行的折叠态；缺省走会话态。 */
  turnKey?: string;
  /** 本行的稳定标识（{@link timelineNodeKeys}）——标记中段插入不再位移它。 */
  rowKey: string;
  /** 所属对话（= conversationId）：仅 browser 单步结果用它懒加载关键帧。 */
  conversationId?: string | null;
}) {
  if (step.kind === "reasoning") {
    return (
      <InlineReasoning
        text={step.text}
        streaming={streaming}
        persistKey={turnKey ? `${turnKey}:reason:${rowKey}` : null}
      />
    );
  }
  if (step.kind === "content") {
    return (
      <Markdown
        content={step.text}
        citations={citations}
        citationToDisplay={citationToDisplay}
        knownLedgerIds={knownLedgerIds}
        evidenceLedger={evidenceLedger}
        isStreaming={streaming}
      />
    );
  }
  if (step.kind === "rework") {
    return (
      <span className="inline-flex items-center rounded-full border border-border bg-muted/40 px-2 py-0.5 text-xs text-muted-foreground">
        引用/格式核验后已重写
      </span>
    );
  }
  // Positional markers (team/checkpoint/ask/plan_review) are resolved in the timeline
  // map, never routed here — only a `tool` step reaches this tail.
  if (step.kind === "tool")
    return (
      <ToolLine step={step} turnKey={turnKey} conversationId={conversationId} />
    );
  return null;
}

export function ProcessTimeline({
  process,
  isStreaming,
  citations,
  citationToDisplay,
  knownLedgerIds = null,
  evidenceLedger = null,
  composingTool,
  fallbackContent,
  messageId,
  journal,
  conversationId,
  checkpoints,
  nonBlockingAsks,
  planReviews,
  teamPreviews,
  /** When false, never collapse reasoning/tool rows into a summary (run-detail panel).
   * Default true keeps CEO bubble chrome. */
  collapseProcessSteps = true,
}: {
  process: ProcessStep[];
  isStreaming: boolean;
  citations: Citation[];
  citationToDisplay?: ReadonlyMap<number, number>;
  knownLedgerIds?: ReadonlySet<string> | null;
  evidenceLedger?: readonly TurnEvidenceLedgerEntry[] | null;
  composingTool: { toolName: string; chars: number } | null;
  fallbackContent: string;
  messageId?: string;
  journal?: ExecutionJournal;
  conversationId: string | null;
  checkpoints: CheckpointDisplay[];
  nonBlockingAsks: NonBlockingAskDisplay[];
  planReviews: PlanReviewDisplay[];
  teamPreviews: TeamPreviewDisplay[];
  collapseProcessSteps?: boolean;
}) {
  const last = process[process.length - 1];
  const hasContentStep = process.some((s) => s.kind === "content");
  const showThinkingTail =
    isStreaming &&
    !composingTool &&
    last?.kind === "tool" &&
    last.status !== "running";

  const nodes = groupToolRuns(process);
  // 稳定 key（时间线一期）：insertBeforeTeam 中段插入不再位移后续行的 React key。
  const nodeKeys = timelineNodeKeys(nodes);

  const hasProcessSteps = nodes.some(isProcessNode);
  const { reasoningCount, toolCount } = countProcessStats(nodes);
  const shouldCollapseProcess =
    collapseProcessSteps &&
    !isStreaming &&
    hasProcessSteps &&
    !(reasoningCount === 1 && toolCount === 0);
  const [processExpanded, toggleProcess] = useStreamAwareDisclosure(
    messageId ? `${messageId}:process` : null,
    isStreaming,
    { settledDefault: false },
  );
  const processSummary = formatProcessSummary(reasoningCount, toolCount);

  // 协作图应在 CEO 回复下方: when prose only exists as fallbackContent (no content
  // step), slot it before the first team/graph_append marker — never after the
  // whole timeline (that put the graph above the CEO lead-in).
  const fallbackBeforeTeamIdx =
    !hasContentStep && fallbackContent
      ? nodes.findIndex((n) => n.kind === "team" || n.kind === "graph_append")
      : -1;
  const showFallbackAfter =
    !hasContentStep && Boolean(fallbackContent) && fallbackBeforeTeamIdx < 0;

  const renderFallback = (key: string) => (
    <Markdown
      key={key}
      content={fallbackContent}
      citations={citations}
      citationToDisplay={citationToDisplay}
      knownLedgerIds={knownLedgerIds}
      evidenceLedger={evidenceLedger}
      isStreaming={isStreaming}
    />
  );

  const renderNode = (node: TimelineNode, i: number) => {
    const live = isStreaming && i === nodes.length - 1;
    const nodeKey = nodeKeys[i];
    if (node.kind === "team") {
      return messageId ? (
        <InlineTeamGraph
          key={nodeKey}
          messageId={messageId}
          executionId={node.execution_id}
          journal={journal}
        />
      ) : null;
    }
    if (node.kind === "graph_append") {
      const append = node as typeof node & {
        act_kind?: string;
        authorized_by?: string;
      };
      return (
        <GraphAppendAnchor
          key={nodeKey}
          hostMessageId={node.host_message_id}
          addedCount={node.added_count}
          actKind={append.act_kind}
          authorizedBy={append.authorized_by}
        />
      );
    }
    if (
      node.kind === "checkpoint" ||
      node.kind === "ask" ||
      node.kind === "plan_review" ||
      node.kind === "team_preview" ||
      node.kind === "escalation" ||
      node.kind === "approval" ||
      node.kind === "delegation_authorization" ||
      node.kind === "stage_card"
    ) {
      return (
        <div key={nodeKey}>
          {renderTimelineInteractionCard(
            node.kind,
            node,
            {
              checkpoints,
              nonBlockingAsks,
              planReviews,
              teamPreviews,
            },
            {
              messageId: messageId ?? "",
              conversationId,
              interactive: isStreaming,
            },
          )}
        </div>
      );
    }
    if (node.kind === "tool-group") {
      return (
        <ToolLineGroup
          key={nodeKey}
          tools={node.tools}
          isStreaming={live}
          turnKey={messageId}
          groupKey={nodeKey}
          conversationId={conversationId}
        />
      );
    }
    const step: ProcessStep = node.kind === "tool" ? node.step : node;
    return (
      <ProcessRow
        key={nodeKey}
        step={step}
        streaming={live}
        citations={citations}
        citationToDisplay={citationToDisplay}
        knownLedgerIds={knownLedgerIds}
        evidenceLedger={evidenceLedger}
        turnKey={messageId}
        rowKey={nodeKey}
        conversationId={conversationId}
      />
    );
  };

  return (
    <div className="space-y-2">
      {nodes.map((node, i) => {
        const prefix =
          i === fallbackBeforeTeamIdx
            ? renderFallback("fallback-before-team")
            : null;
        if (shouldCollapseProcess) {
          const isFirstProcess =
            isProcessNode(node) && !nodes.slice(0, i).some(isProcessNode);

          if (!processExpanded) {
            if (isProcessNode(node)) {
              if (!isFirstProcess) return null;
              return (
                <Fragment key={`sum-${nodeKeys[i]}`}>
                  {prefix}
                  <button
                    type="button"
                    onClick={toggleProcess}
                    className="inline-flex items-center gap-1 text-sm text-muted-foreground"
                  >
                    {processSummary}
                    <ChevronRight className="size-4 shrink-0" aria-hidden />
                  </button>
                </Fragment>
              );
            }
          } else if (isFirstProcess) {
            return (
              <Fragment key="process-expanded">
                {prefix}
                <button
                  type="button"
                  onClick={toggleProcess}
                  className="inline-flex items-center gap-1 text-sm text-muted-foreground"
                >
                  {processSummary}
                  <ChevronDown className="size-4 shrink-0" aria-hidden />
                </button>
                {renderNode(node, i)}
              </Fragment>
            );
          }
        }
        if (prefix) {
          return (
            <Fragment key={`wrap-${nodeKeys[i]}`}>
              {prefix}
              {renderNode(node, i)}
            </Fragment>
          );
        }
        return renderNode(node, i);
      })}
      {/* 无 team 标记的图兜底已移除（时间线一期）：多 Agent 回合必有 `team` 标记
          （live 盖章 + reload journal 补齐），图只在标记槽渲染。 */}
      {showFallbackAfter && renderFallback("fallback-after")}
      {isStreaming && composingTool && (
        <ComposingToolLine tool={composingTool} />
      )}
      {showThinkingTail && (
        <span className="inline-flex items-center gap-2 text-sm text-muted-foreground">
          <ThinkingDots />
          Thinking…
        </span>
      )}
    </div>
  );
}

/** Re-export for consumers that imported from ProcessTimeline. */
export { ComposingToolLine } from "@/components/chat/ToolLine";
