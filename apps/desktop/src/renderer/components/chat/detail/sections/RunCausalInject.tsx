import { Button } from "@/components/ui";
import {
  type InjectInEdgeView,
  filterInjectInEdges,
  injectEdgeLabel,
} from "@/lib/causalInject";
import { usePersistentDisclosure } from "@/stores/disclosure";
import type { AgentState, RunNode } from "@/stores/execution";
import type { AuditCausalGraph } from "@agentcore/contract-rest-types/audit";
import { ArrowRight, ChevronDown, ChevronRight } from "lucide-react";
import { RunStatusDot } from "./shared";

function InjectEdgeRow({
  edge,
  graph,
  runs,
  agents,
  currentRunId,
  onSelect,
}: {
  edge: InjectInEdgeView;
  graph: AuditCausalGraph | null | undefined;
  runs: RunNode[];
  agents: AgentState[];
  currentRunId: string;
  onSelect: (runId: string, title?: string) => void;
}) {
  const { sourceRole, sourceTask, targetRole } = injectEdgeLabel(
    edge,
    graph,
    runs,
    agents,
  );
  const sourceRun = runs.find((r) => r.id === edge.from);

  return (
    <Button
      variant="ghost"
      onClick={() => onSelect(edge.from, sourceRole)}
      className="h-auto w-full justify-start gap-2 rounded-lg bg-muted px-2.5 py-2 text-xs hover:bg-accent"
    >
      <span className="flex w-full min-w-0 items-center gap-2 text-left">
        {sourceRun && <RunStatusDot status={sourceRun.status} />}
        <span className="min-w-0 flex-1">
          <span className="font-medium text-foreground">{sourceRole}</span>
          {sourceTask && (
            <span className="mt-0.5 block truncate text-muted-foreground">
              {sourceTask}
            </span>
          )}
        </span>
        <span className="flex shrink-0 items-center gap-1 text-muted-foreground">
          <span className="rounded bg-background px-1.5 py-0.5">注入</span>
          <ArrowRight size={12} />
          <span className="font-medium text-foreground">
            {targetRole}
            {edge.to === currentRunId ? "（当前）" : ""}
          </span>
        </span>
      </span>
    </Button>
  );
}

/**
 * Run 详情「关系」区段内的「数据从哪来」子块：仅展示当前 run 的 inject 入边。
 */
export function RunCausalInjectBlock({
  runId,
  graph,
  runs,
  agents,
  onSelect,
  sceneKey,
}: {
  runId: string;
  graph: AuditCausalGraph | null | undefined;
  runs: RunNode[];
  agents: AgentState[];
  onSelect: (runId: string, title?: string) => void;
  sceneKey: string;
}) {
  const edges = filterInjectInEdges(graph, runId);
  const [open, setOpen] = usePersistentDisclosure(sceneKey, false);

  if (edges.length === 0) return null;

  const collapsedSummary = edges
    .map((edge) => injectEdgeLabel(edge, graph, runs, agents).sourceRole)
    .join("、");

  return (
    <div className="rounded-lg border border-border/60 bg-background/40 px-2 py-1.5">
      <Button
        variant="ghost"
        onClick={() => setOpen((v) => !v)}
        className="h-auto w-full justify-start gap-2 px-1 py-1 hover:bg-transparent"
      >
        <span className="flex w-full items-center gap-2 text-left text-xs">
          {open ? (
            <ChevronDown size={12} className="shrink-0 text-muted-foreground" />
          ) : (
            <ChevronRight
              size={12}
              className="shrink-0 text-muted-foreground"
            />
          )}
          <span className="flex-1 font-medium text-foreground">数据从哪来</span>
          <span className="tabular-nums text-muted-foreground">
            {edges.length} 条
          </span>
        </span>
      </Button>

      {!open && (
        <p className="px-1 pb-0.5 text-xs text-muted-foreground">
          {collapsedSummary} → 本 run
        </p>
      )}

      {open && (
        <div className="mt-1.5 space-y-1.5">
          {edges.map((edge) => (
            <InjectEdgeRow
              key={`${edge.from}:${edge.to}`}
              edge={edge}
              graph={graph}
              runs={runs}
              agents={agents}
              currentRunId={runId}
              onSelect={onSelect}
            />
          ))}
          <p className="px-1 text-xs text-muted-foreground">
            详情见上方「收到的上下文」
          </p>
        </div>
      )}
    </div>
  );
}
