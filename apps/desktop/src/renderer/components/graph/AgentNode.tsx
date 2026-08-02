import {
  Tooltip,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { Handle, type NodeProps, Position } from "@xyflow/react";
import { AgentNodeCardFace } from "./agentNode/AgentNodeFace";
import { AgentNodePeek } from "./agentNode/AgentNodePeek";
import { buildAgentNodePresentation } from "./agentNode/presentation";
import type { AgentNodeData } from "./agentNode/shared";
import { graphNodeDimClass, useGraphNodeDimmed } from "./graphHover";
import {
  type AgentNodeShell,
  useAgentNodeLive,
  useGraphDocumentMode,
} from "./graphLive";
import { useTerminalFlash } from "./useTerminalFlash";

export type { AgentNodeData } from "./agentNode/shared";

export function AgentNode({ data }: NodeProps) {
  const documentMode = useGraphDocumentMode();
  const live = useAgentNodeLive(data as AgentNodeShell);
  const d = documentMode ? live : (data as AgentNodeData);
  const p = buildAgentNodePresentation(d);
  const horizontal = d.handleDirection === "horizontal";
  const flashing = useTerminalFlash(d.status);
  const flashColor =
    d.status === "failed" ? "var(--destructive)" : "var(--success)";
  const dimmed = useGraphNodeDimmed();

  return (
    <>
      <Handle
        type="target"
        position={horizontal ? Position.Left : Position.Top}
        className="!bg-border"
      />
      <div className={graphNodeDimClass(dimmed)}>
        <div
          className="animate-graph-node-enter"
          style={{ animationDelay: `${p.enterDelay}ms` }}
        >
          <Tooltip>
            <TooltipTrigger asChild>
              <AgentNodeCardFace
                d={d}
                p={p}
                flashColor={flashColor}
                flashing={flashing}
              />
            </TooltipTrigger>
            <TooltipContent side="right" align="start" className="w-72">
              <AgentNodePeek d={d} p={p} />
            </TooltipContent>
          </Tooltip>
        </div>
      </div>
      <Handle
        type="source"
        position={horizontal ? Position.Right : Position.Bottom}
        className="!bg-border"
      />
    </>
  );
}
