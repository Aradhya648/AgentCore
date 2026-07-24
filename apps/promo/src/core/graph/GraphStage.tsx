import { TooltipProvider } from "@/components/ui/tooltip";
import {
  Background,
  type Edge,
  type Node,
  ReactFlow,
  ReactFlowProvider,
} from "@xyflow/react";
import type { DebateState } from "./graphState";
import { PromoFlowEdge } from "./PromoFlowEdge";
import { PromoAgentNode, PromoEndpointNode } from "./PromoNodes";

/*
 * Reusable, deterministic renderer for a collaboration graph. Takes a
 * fully-derived per-frame {nodes, edges, debate} (built by graphState) and lays
 * it out centered inside the given box, scaled to fit. Used full-bleed by the
 * standalone GraphScene composition and inside the desktop shell's main area by
 * the assembled promo — same pixels either way.
 *
 * graphW / graphH are required (caller passes the baked ELK bbox) — core does
 * not import video-package demo layout.
 */

const nodeTypes = {
  agent: PromoAgentNode,
  userInput: PromoEndpointNode,
  captain: PromoEndpointNode,
};
const edgeTypes = { flow: PromoFlowEdge };

interface Props {
  nodes: Node[];
  edges: Edge[];
  debate: DebateState | null;
  frame: number;
  boxWidth: number;
  boxHeight: number;
  /** Graph bbox to fit (baked ELK width/height from the video or still package). */
  graphW: number;
  graphH: number;
  /** Horizontal / vertical breathing room kept around the graph bbox. */
  padX?: number;
  padY?: number;
  showBackground?: boolean;
  /** Promo stills: render the 对射 axis as a glowing, warm→cool gradient firing
   * line (cinematic). The film leaves this off for the plain product connector. */
  cinematic?: boolean;
}

export function GraphStage({
  nodes,
  edges,
  debate,
  frame,
  boxWidth,
  boxHeight,
  graphW,
  graphH,
  padX = 140,
  padY = 180,
  showBackground = true,
  cinematic = false,
}: Props) {
  const W = graphW;
  const H = graphH;
  const zoom = Math.min(1, (boxWidth - padX) / W, (boxHeight - padY) / H);
  const scaledW = W * zoom;
  const scaledH = H * zoom;
  const left = (boxWidth - scaledW) / 2;
  const top = (boxHeight - scaledH) / 2;

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden" }}>
      <div
        style={{
          position: "absolute",
          left,
          top,
          width: W,
          height: H,
          transform: `scale(${zoom})`,
          transformOrigin: "top left",
        }}
      >
        <TooltipProvider>
          {debate && (
            <DebateConnector
              debate={debate}
              frame={frame}
              cinematic={cinematic}
              w={W}
              h={H}
            />
          )}
          <ReactFlowProvider>
            <ReactFlow
              nodes={nodes}
              edges={edges}
              nodeTypes={nodeTypes}
              edgeTypes={edgeTypes}
              defaultViewport={{ x: 0, y: 0, zoom: 1 }}
              fitView={false}
              proOptions={{ hideAttribution: true }}
              nodesDraggable={false}
              nodesConnectable={false}
              elementsSelectable={false}
              panOnDrag={false}
              zoomOnScroll={false}
              zoomOnPinch={false}
              zoomOnDoubleClick={false}
              style={{ width: W, height: H, background: "transparent" }}
            >
              {showBackground && <Background gap={20} size={1} />}
            </ReactFlow>
          </ReactFlowProvider>
        </TooltipProvider>
      </div>
    </div>
  );
}

/**
 * The 辩论对射 connector: a dotted line between the debate pair with particles
 * fired both ways. Drawn in graph coords (shared with ReactFlow), behind the
 * opaque cards so particles read as emerging from one card into the other.
 *
 * `cinematic` (promo stills) makes it the image's centerpiece: a blurred glow
 * underlay, a thicker brighter axis stroked with a warm→cool gradient (正营 top ↔
 * 反营 bottom — the two camps reading at a glance), and denser particles tinted to
 * their camp. The film keeps the plain single-color product connector.
 */
function DebateConnector({
  debate,
  frame,
  cinematic = false,
  w,
  h,
}: {
  debate: DebateState;
  frame: number;
  cinematic?: boolean;
  /* SVG viewport = the rendered graph's bbox (NOT the demo's): the axis lives in
   * graph coords, so a smaller hardcoded viewport would clip it out in any bbox
   * larger than the demo (e.g. the bigteam panorama). */
  w: number;
  h: number;
}) {
  if (!debate.active) return null;
  const { x1, y1, x2, y2 } = debate;
  const dx = x2 - x1;
  const dy = y2 - y1;

  // Two streams crossing in opposite directions (对射), looping every ~36 frames.
  const period = 36;
  const phase = (frame % period) / period;
  const perDir = cinematic ? 3 : 2;
  const stream = (base: number) =>
    Array.from({ length: perDir }, (_, i) => (base + i / perDir) % 1);
  const dots = [
    ...stream(phase).map((f) => ({ f, key: `d${f}` })),
    ...stream(1 - phase).map((f) => ({ f, key: `u${f}` })),
  ];

  // Warm (正营/p1) → cool (反营/p2) so the two camps read instantly.
  const gradId = "debate-axis-grad";
  const axisStroke = cinematic ? `url(#${gradId})` : "var(--primary)";

  return (
    <svg
      width={w}
      height={h}
      style={{ position: "absolute", left: 0, top: 0, pointerEvents: "none" }}
      role="presentation"
    >
      {cinematic && (
        <defs>
          <linearGradient
            id={gradId}
            x1={x1}
            y1={y1}
            x2={x2}
            y2={y2}
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="var(--warning)" />
            <stop offset="50%" stopColor="var(--primary)" />
            <stop offset="100%" stopColor="var(--primary)" />
          </linearGradient>
        </defs>
      )}
      {cinematic && (
        <line
          x1={x1}
          y1={y1}
          x2={x2}
          y2={y2}
          stroke={axisStroke}
          strokeWidth={11}
          strokeLinecap="round"
          opacity={0.22}
          style={{ filter: "blur(4px)" }}
        />
      )}
      <line
        x1={x1}
        y1={y1}
        x2={x2}
        y2={y2}
        stroke={axisStroke}
        strokeWidth={cinematic ? 2.5 : 2}
        strokeDasharray="2 4"
        opacity={cinematic ? 0.85 : 0.55}
      />
      {dots.map((d) => {
        const edge = Math.min(d.f, 1 - d.f);
        const opacity = Math.min(1, edge / 0.12);
        const fill =
          cinematic && d.f < 0.5 ? "var(--warning)" : "var(--primary)";
        return (
          <circle
            key={d.key}
            cx={x1 + d.f * dx}
            cy={y1 + d.f * dy}
            r={cinematic ? 4 : 3}
            fill={fill}
            opacity={opacity}
          />
        );
      })}
    </svg>
  );
}
