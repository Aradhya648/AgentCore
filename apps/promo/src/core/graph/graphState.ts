import type { Edge, Node } from "@xyflow/react";
import { typeOut } from "../motion/primitives";

/*
 * Frame evaluator for collaboration-graph promo segments: given a graph spec
 * (nodes / edges / positions / wave schedule / streaming copy / debate axis) and
 * the current scene-local frame, produce ReactFlow node/edge state for GraphStage.
 *
 * Video-specific schedule tables and node ids live in the video package — this
 * module must not import videos/.
 */

export interface SchedEntry {
  enter: number;
  run: number;
  done: number;
}

export interface GraphNodeSpec {
  id: string;
  type: string;
  data: Record<string, unknown>;
}

export interface GraphEdgeSpec {
  id: string;
  source: string;
  target: string;
  kind: string;
}

/** 对射 axis endpoints + active window (node ids resolved via positions). */
export interface DebateAxisSpec {
  topNodeId: string;
  botNodeId: string;
  /** Offset from node origin to axis x (card half-width; was 105). */
  centerXOffset: number;
  /** Offset from node origin to axis y (card mid-height; was 66). */
  centerYOffset: number;
  activeFrom: number;
  activeTo: number;
}

export interface GraphEvalSpec {
  nodes: GraphNodeSpec[];
  edges: GraphEdgeSpec[];
  positions: Record<string, { x: number; y: number }>;
  sched: Record<string, SchedEntry>;
  stream: Record<string, string>;
  durationMs: Record<string, number>;
  inputId: string;
  captainId: string;
  inputEnter: number;
  captainEnter: number;
  debate: DebateAxisSpec;
}

export interface CaptainOverride {
  status: string;
  preview?: string;
  /** Scene-local frame the 汇聚点 reaches its terminal state (drives 绿闪). */
  terminalFrame?: number | null;
}

export interface DebateState {
  /* 对射 axis as a generic segment p1(x1,y1) → p2(x2,y2): vertical for leftright
   * layouts (x1===x2, debaters stacked in a column), horizontal for top-down ones
   * (y1===y2, debaters in a row). p1 is the 正营 end (warm in the cinematic gradient). */
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  active: boolean;
}

export interface GraphState {
  nodes: Node[];
  edges: Edge[];
  debate: DebateState;
}

function nodePosition(
  positions: Record<string, { x: number; y: number }>,
  id: string,
): { x: number; y: number } {
  return positions[id] ?? { x: 0, y: 0 };
}

function enterOf(spec: GraphEvalSpec, id: string): number {
  if (id === spec.inputId) return spec.inputEnter;
  if (id === spec.captainId) return spec.captainEnter;
  return spec.sched[id]?.enter ?? 0;
}

function statusAt(spec: GraphEvalSpec, id: string, frame: number): string {
  if (id === spec.inputId) return "completed";
  if (id === spec.captainId) return "pending";
  const s = spec.sched[id];
  if (!s) return "pending";
  if (frame < s.run) return "pending";
  if (frame < s.done) return "running";
  return "completed";
}

function edgeFlow(spec: GraphEvalSpec, targetId: string, frame: number): number {
  const s = spec.sched[targetId];
  if (!s) return 0;
  return frame >= s.run - 9 && frame < s.done + 2 ? 1 : 0;
}

/**
 * Build the ReactFlow node/edge state for the graph at `frame` (scene-local).
 * `opts.captain` overrides the 汇聚点 (used by AnswerScene where it lights up).
 */
export function buildGraphState(
  frame: number,
  fps: number,
  spec: GraphEvalSpec,
  opts: { captain?: CaptainOverride } = {},
): GraphState {
  const nodes: Node[] = spec.nodes.map((n) => {
    const isCaptain = n.id === spec.captainId;
    let status = statusAt(spec, n.id, frame);
    let preview = "";
    let captainPreview: string | undefined;
    let terminalFrame: number | null = spec.sched[n.id]?.done ?? null;
    if (isCaptain && opts.captain) {
      status = opts.captain.status;
      captainPreview = opts.captain.preview;
      terminalFrame = opts.captain.terminalFrame ?? null;
    }
    const s = spec.sched[n.id];
    const running = status === "running";
    if (running && spec.stream[n.id]) {
      preview = typeOut(spec.stream[n.id], frame, s?.run ?? 0, fps);
    }
    const durationMs =
      status === "completed" ? spec.durationMs[n.id] : undefined;
    return {
      id: n.id,
      type: n.type,
      position: nodePosition(spec.positions, n.id),
      data: {
        ...n.data,
        status,
        isAnimating: running,
        ...(isCaptain
          ? { preview: captainPreview ?? "" }
          : { outputPreview: preview }),
        ...(durationMs ? { durationMs } : {}),
        _enterFrame: enterOf(spec, n.id),
        _terminalFrame: terminalFrame,
        _ok: true,
        handleDirection: "horizontal",
      },
    } as Node;
  });

  const edges: Edge[] = spec.edges.map((e) => {
    const appear =
      Math.max(enterOf(spec, e.source), enterOf(spec, e.target)) + 6;
    const enterOpacity =
      frame >= appear
        ? 1
        : frame >= appear - 9
          ? (frame - (appear - 9)) / 9
          : 0;
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: "flow",
      data: {
        flow: edgeFlow(spec, e.target, frame),
        kind: e.kind,
        enterOpacity,
      },
    } as Edge;
  });

  const top = nodePosition(spec.positions, spec.debate.topNodeId);
  const bot = nodePosition(spec.positions, spec.debate.botNodeId);
  const cx = top.x + spec.debate.centerXOffset;
  const debate: DebateState = {
    x1: cx,
    y1: top.y + spec.debate.centerYOffset,
    x2: cx,
    y2: bot.y + spec.debate.centerYOffset,
    active:
      frame >= spec.debate.activeFrom && frame < spec.debate.activeTo,
  };

  return { nodes, edges, debate };
}
