import { Button } from "@/components/ui";
import type { AgentState, RunNode } from "@/stores/execution";
import { CornerDownRight } from "lucide-react";
import { RunStatusDot } from "./shared";

/** Total nested runs under a run (direct children + their descendants). 阶段2
 * caps nesting at CEO → worker → sub-worker, so this stays shallow, but it is
 * written generally to match the indented tree it labels. Continuation edges
 * (`continuesRunId != null`, 辩论轮次 / 热修) are skipped — they are a VERSION chain, not a
 * delegated sub-task, so a debater's later rounds never count as its 子任务. */
export function countDescendants(runs: RunNode[], parentId: string): number {
  return runs
    .filter((r) => r.parentRunId === parentId && r.continuesRunId == null)
    .reduce((n, r) => n + 1 + countDescendants(runs, r.id), 0);
}

/**
 * The delegated sub-task tree under a run (阶段2 嵌套子任务), rendered as an
 * indented list: each row drills into that sub-worker's detail, and its own
 * children nest one level deeper behind a guide rail. Reuses the shared
 * run-detail focus so the panel and graph stay in sync.
 */
export function SubtaskTree({
  parentId,
  runs,
  agents,
  depth,
  onSelect,
}: {
  parentId: string;
  runs: RunNode[];
  agents: AgentState[];
  depth: number;
  onSelect: (runId: string, title?: string) => void;
}) {
  const children = runs.filter(
    (r) => r.parentRunId === parentId && r.continuesRunId == null,
  );
  if (children.length === 0) return null;
  return (
    <div
      className={
        depth > 0 ? "ml-2 space-y-1 border-l border-border pl-2" : "space-y-1"
      }
    >
      {children.map((r) => {
        const role = agents.find((a) => a.id === r.agentId)?.role ?? r.agentId;
        return (
          <div key={r.id} className="space-y-1">
            <Button
              variant="ghost"
              onClick={() => onSelect(r.id, role)}
              className="h-auto w-full justify-start gap-2 rounded-lg bg-muted px-2.5 py-1.5 text-xs hover:bg-accent"
            >
              <span className="flex w-full items-center gap-2 text-left">
                <CornerDownRight
                  size={12}
                  className="shrink-0 text-muted-foreground/60"
                />
                <RunStatusDot status={r.status} />
                <span className="shrink-0 font-medium text-foreground">
                  {role}
                </span>
                <span className="flex-1 truncate text-muted-foreground">
                  {r.task}
                </span>
              </span>
            </Button>
            <SubtaskTree
              parentId={r.id}
              runs={runs}
              agents={agents}
              depth={depth + 1}
              onSelect={onSelect}
            />
          </div>
        );
      })}
    </div>
  );
}

/** A labelled list of related runs (依赖 / 后续 / 上级) — each row drills into
 * that run, reusing the shared run-detail focus so the panel and graph stay in
 * sync. */
export function RunRefGroup({
  label,
  runs,
  agents,
  onSelect,
}: {
  label: string;
  runs: RunNode[];
  agents: AgentState[];
  onSelect: (runId: string, title?: string) => void;
}) {
  return (
    <div>
      <p className="mb-1 text-xs text-muted-foreground">{label}</p>
      <div className="space-y-1">
        {runs.map((r) => {
          const role =
            agents.find((a) => a.id === r.agentId)?.role ?? r.agentId;
          return (
            <Button
              key={r.id}
              variant="ghost"
              onClick={() => onSelect(r.id, role)}
              className="h-auto w-full justify-start gap-2 rounded-lg bg-muted px-2.5 py-1.5 text-xs hover:bg-accent"
            >
              <span className="flex w-full items-center gap-2 text-left">
                <RunStatusDot status={r.status} />
                <span className="shrink-0 font-medium text-foreground">
                  {role}
                </span>
                <span className="flex-1 truncate text-muted-foreground">
                  {r.task}
                </span>
              </span>
            </Button>
          );
        })}
      </div>
    </div>
  );
}
