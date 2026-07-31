/**
 * Definition-canvas node views for user workflows.
 * Intentionally separate from collaboration-graph `components/graph/*`.
 */

import { cn } from "@/lib/utils";
import type { WorkflowNodeKind } from "@/services/workflowDefinition";
import { Handle, type Node, type NodeProps, Position } from "@xyflow/react";
import { Hand, UserRound } from "lucide-react";

export type WorkflowCanvasNodeData = {
  kind: WorkflowNodeKind;
  title: string;
  subtitle?: string;
  selected?: boolean;
};

export type WorkflowCanvasNode = Node<WorkflowCanvasNodeData, "workflowNode">;

function WorkflowNodeView({ data, selected }: NodeProps<WorkflowCanvasNode>) {
  const isGate = data.kind === "human_gate";
  return (
    <div
      className={cn(
        "min-w-[180px] max-w-[240px] rounded-xl border bg-card px-3 py-2.5 shadow-sm",
        selected ? "border-primary ring-1 ring-ring" : "border-border",
        isGate && "border-dashed",
      )}
    >
      <Handle
        type="target"
        position={Position.Left}
        className="!size-2.5 !border-border !bg-muted-foreground"
      />
      <div className="flex items-start gap-2">
        <span
          className={cn(
            "mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-lg",
            isGate
              ? "bg-warning/15 text-warning"
              : "bg-primary/10 text-primary",
          )}
        >
          {isGate ? <Hand size={14} /> : <UserRound size={14} />}
        </span>
        <div className="min-w-0">
          <p className="truncate text-sm font-medium text-foreground">
            {data.title || (isGate ? "等人关卡" : "队员步骤")}
          </p>
          {data.subtitle ? (
            <p className="mt-0.5 line-clamp-2 text-xs text-muted-foreground">
              {data.subtitle}
            </p>
          ) : (
            <p className="mt-0.5 text-xs text-muted-foreground">
              {isGate ? "步骤后等人确认" : "角色 · 任务"}
            </p>
          )}
        </div>
      </div>
      <Handle
        type="source"
        position={Position.Right}
        className="!size-2.5 !border-border !bg-muted-foreground"
      />
    </div>
  );
}

export const workflowNodeTypes = {
  workflowNode: WorkflowNodeView,
};
