import { Badge } from "@/components/ui/Badge";
import {
  STATUS_TONE,
} from "@/components/conversation-replay/shared";
import { cn } from "@/lib/utils";
import type { ReplayRun } from "@/services/adminObservability";
import { ChevronDown, ChevronRight, Users } from "lucide-react";
import { useMemo, useState } from "react";

/**
 * Static preview-level collaboration graph for admin replay.
 * Visual echo of desktop InlineTeamGraph — no live canvas, no maximize/replay CTAs.
 * Node click → parent opens right dock with that run's detail.
 */
export function InlineTeamGraph({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs: ReplayRun[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const [expanded, setExpanded] = useState(true);

  const { roots, byParent, failed, completed } = useMemo(() => {
    const map = new Map<string | null, ReplayRun[]>();
    for (const r of runs) {
      const key = r.parent_run_id ?? null;
      const list = map.get(key) ?? [];
      list.push(r);
      map.set(key, list);
    }
    const known = new Set(runs.map((r) => r.run_id));
    const orphanRoots = runs.filter(
      (r) => r.parent_run_id != null && !known.has(r.parent_run_id),
    );
    const top =
      (map.get(null) ?? []).length > 0
        ? (map.get(null) ?? [])
        : orphanRoots.length > 0
          ? orphanRoots
          : runs;
    return {
      roots: top,
      byParent: map,
      failed: runs.filter((r) => r.status === "failed").length,
      completed: runs.filter((r) => r.status === "completed").length,
    };
  }, [runs]);

  if (runs.length === 0) return null;

  return (
    <div
      className="overflow-hidden rounded-xl border border-border bg-card"
      onClick={(e) => e.stopPropagation()}
      onKeyDown={(e) => e.stopPropagation()}
    >
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className="flex w-full items-center gap-2 px-3 py-2 text-left outline-none hover:bg-muted/40 focus-visible:ring-2 focus-visible:ring-ring"
      >
        <Users size={14} className="shrink-0 text-primary" />
        <span className="min-w-0 flex-1 text-sm text-foreground">
          协作 · {runs.length} 队员
          <span className="ml-1.5 text-muted-foreground">
            {completed}/{runs.length} 完成
            {failed > 0 ? ` · ${failed} 失败` : ""}
          </span>
        </span>
        {expanded ? (
          <ChevronDown size={14} className="shrink-0 text-muted-foreground" />
        ) : (
          <ChevronRight size={14} className="shrink-0 text-muted-foreground" />
        )}
      </button>

      {expanded && (
        <div className="border-border border-t px-3 py-3">
          <p className="mb-2 text-muted-foreground text-xs">
            点节点在右坞查看队员详情
          </p>
          <ul className="space-y-1.5">
            {roots.map((r) => (
              <GraphNode
                key={r.run_id}
                run={r}
                depth={0}
                byParent={byParent}
                selectedRunId={selectedRunId}
                onSelectRun={onSelectRun}
              />
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}

function GraphNode({
  run,
  depth,
  byParent,
  selectedRunId,
  onSelectRun,
}: {
  run: ReplayRun;
  depth: number;
  byParent: Map<string | null, ReplayRun[]>;
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const children = byParent.get(run.run_id) ?? [];
  const active = selectedRunId === run.run_id;
  const label = run.role || run.agent_id;

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelectRun(run.run_id)}
        className={cn(
          "flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
          active
            ? "border-primary/50 bg-primary/10 ring-1 ring-primary/30"
            : "border-border/70 bg-muted/20 hover:bg-muted/40",
        )}
        style={{ marginLeft: depth * 14 }}
      >
        <Badge
          tone={STATUS_TONE[run.status] ?? "neutral"}
          className="mt-0.5 shrink-0"
        >
          {run.status}
        </Badge>
        <span className="min-w-0 flex-1 text-sm font-medium text-foreground">
          {label}
          {run.kind !== "agent" && (
            <span className="ml-1.5 font-normal text-muted-foreground text-xs">
              {run.kind}
            </span>
          )}
        </span>
      </button>
      {children.length > 0 && (
        <ul className="mt-1.5 space-y-1.5">
          {children.map((c) => (
            <GraphNode
              key={c.run_id}
              run={c}
              depth={depth + 1}
              byParent={byParent}
              selectedRunId={selectedRunId}
              onSelectRun={onSelectRun}
            />
          ))}
        </ul>
      )}
    </li>
  );
}
