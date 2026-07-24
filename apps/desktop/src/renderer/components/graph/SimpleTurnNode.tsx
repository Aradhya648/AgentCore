import { Handle, type NodeProps, Position } from "@xyflow/react";
import { Loader2, MessageSquare } from "lucide-react";
import { useState } from "react";

/**
 * 简单回合竖排退化卡（前端UX设计.md §6.1）: a single-agent turn
 * (`executionId === null`) on the persistent conversation canvas. A team turn folds
 * into a {@link import("./TurnSummaryNode")} DAG-summary; a plain Q&A has no team to
 * draw, so it degenerates to a light card in the same vertical spine — the canvas
 * stays a faithful record of the whole conversation without faking a graph.
 *
 * Card face shows the prompt as title and a short answer snippet; click opens the
 * side-panel `simple-turn` Q&A tab with the full prompt + answer (不离开画布).
 */
export interface SimpleTurnData {
  prompt: string;
  answer: string;
  running: boolean;
  /** 轻入场 (前端UX设计.md §六): true only when this is a genuinely new turn (set by the
   * host on the render it first appears). Captured once at mount so the streaming answer's
   * re-renders never restart or cut the entrance short. */
  enter?: boolean;
  [key: string]: unknown;
}

export function SimpleTurnNode({ data }: NodeProps) {
  const d = data as SimpleTurnData;
  // Capture at mount: a remount (focus switch) / initial open passes enter=false, a new
  // turn passes true; later prop flips (the answer streaming) must not retrigger it.
  const [entered] = useState(d.enter ?? false);
  return (
    <>
      <Handle type="target" position={Position.Top} className="!bg-border" />
      <div
        className={`w-[320px] cursor-pointer rounded-xl border border-border bg-muted/30 px-3.5 py-3 shadow-sm ${
          entered ? "animate-task-card-enter" : ""
        }`}
      >
        <div className="flex items-center gap-2">
          <div className="flex size-7 shrink-0 items-center justify-center rounded-full bg-muted">
            {d.running ? (
              <Loader2 size={14} className="animate-spin text-primary" />
            ) : (
              <MessageSquare size={14} className="text-muted-foreground" />
            )}
          </div>
          <p className="min-w-0 flex-1 truncate text-sm font-medium text-foreground">
            {d.prompt || "直接回答"}
          </p>
        </div>
        {d.answer && (
          <p className="mt-2 line-clamp-2 text-xs leading-snug text-muted-foreground">
            {d.answer}
          </p>
        )}
      </div>
      <Handle type="source" position={Position.Bottom} className="!bg-border" />
    </>
  );
}
