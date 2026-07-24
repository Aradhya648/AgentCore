import { AgentNode } from "@/components/graph/AgentNode";
import { EndpointNode } from "@/components/graph/EndpointNode";
import { StepEdge } from "@/components/graph/StepEdge";
import { TooltipProvider } from "@/components/ui/tooltip";
import {
  Background,
  type Edge,
  type Node,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import { DEMO_DEBATE_EDGES, DEMO_LAYOUT_EDGES, DEMO_NODES } from "./data/demo";
import { DEMO_LAYOUT } from "./data/layout";

/**
 * Phase 0/1 pixel check — renders the real AgentNode / EndpointNode / StepEdge
 * with the demo butterfly DAG, positioned by the precomputed ELK coordinates
 * (data/layout.ts) and typeset in the embedded Inter + Noto Sans SC. The frame
 * is compared against a screenshot of the real running app to confirm
 * pixel-identical rendering.
 *
 * TooltipProvider wraps the canvas because AgentNode's model/depth badges use
 * SimpleTooltip (Radix), which throws without a provider ancestor — the real app
 * mounts one once at its root (App.tsx).
 */

const nodeTypes = {
  agent: AgentNode,
  userInput: EndpointNode,
  captain: EndpointNode,
};
const edgeTypes = { step: StepEdge };

const VIDEO_WIDTH = 1920;
const VIDEO_HEIGHT = 1080;

// Place the graph by its baked ELK slots; particles ride any edge whose target
// is a running node (here the live debate pair) — the climax's primary flow.
const RUNNING = new Set(
  DEMO_NODES.filter((n) => n.data.status === "running").map((n) => n.id),
);

const flowNodes: Node[] = DEMO_NODES.map((n, i) => ({
  id: n.id,
  type: n.type,
  position: DEMO_LAYOUT.positions[n.id] ?? { x: 0, y: 0 },
  data: { ...n.data, handleDirection: "horizontal", enterIndex: i },
}));

const flowEdges: Edge[] = [...DEMO_LAYOUT_EDGES, ...DEMO_DEBATE_EDGES].map((e) => ({
  id: e.id,
  source: e.source,
  target: e.target,
  type: "step",
  data: { kind: e.kind, animated: RUNNING.has(e.target) },
}));

// Center the baked bbox in the 1920×1080 frame at zoom 1 (the 1708-wide graph
// fits without scaling) — a deliberate viewport, not fitView.
const ZOOM = Math.min(1, VIDEO_WIDTH / DEMO_LAYOUT.width);
const VIEWPORT = {
  x: (VIDEO_WIDTH - DEMO_LAYOUT.width * ZOOM) / 2,
  y: (VIDEO_HEIGHT - DEMO_LAYOUT.height * ZOOM) / 2,
  zoom: ZOOM,
};

export const PixelCheck: React.FC = () => {
  return (
    <div
      style={{
        width: VIDEO_WIDTH,
        height: VIDEO_HEIGHT,
        background: "var(--background)",
      }}
    >
      <TooltipProvider>
        <ReactFlowProvider>
          <ReactFlow
            nodes={flowNodes}
            edges={flowEdges}
            nodeTypes={nodeTypes}
            edgeTypes={edgeTypes}
            defaultViewport={VIEWPORT}
            fitView={false}
            proOptions={{ hideAttribution: true }}
            nodesDraggable={false}
            nodesConnectable={false}
            elementsSelectable={false}
            panOnDrag={false}
            zoomOnScroll={false}
            zoomOnPinch={false}
            zoomOnDoubleClick={false}
          >
            <Background gap={20} size={1} />
          </ReactFlow>
        </ReactFlowProvider>
      </TooltipProvider>
    </div>
  );
};
