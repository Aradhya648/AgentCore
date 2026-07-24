import {
  BaseEdge,
  type Edge,
  type EdgeProps,
  getSmoothStepPath,
} from "@xyflow/react";
import { useMemo } from "react";
import { useCurrentFrame } from "remotion";
import { particleFractions } from "../motion/primitives";

/*
 * Frame-driven twin of the desktop StepEdge: identical orthogonal rounded-elbow
 * stroke (same getSmoothStepPath + kind→dash mapping), but the running-edge
 * particles ride the path by frame (useCurrentFrame → getPointAtLength on a
 * detached copy of the exact path) instead of SVG animateMotion's wall clock.
 *
 * data.flow drives the particles: 0 = none, 1 = forward (source→target). The
 * debate edge's two-way exchange is drawn by DebateConnector, not here.
 */
export type PromoFlowEdgeData = Edge<{
  flow?: number;
  kind?: "dep" | "delegate" | "revision";
  /** Entrance fade (0→1) while the edge's endpoints cascade in (7–11s). */
  enterOpacity?: number;
}>;

const PARTICLE_PERIOD = 45;

export function PromoFlowEdge(props: EdgeProps<PromoFlowEdgeData>) {
  const {
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    style,
    data,
  } = props;
  const frame = useCurrentFrame();

  const [edgePath] = getSmoothStepPath({
    sourceX,
    sourceY,
    targetX,
    targetY,
    sourcePosition,
    targetPosition,
    borderRadius: 10,
  });

  // Detached path element for exact arc-length sampling — computed during render
  // (no DOM attachment needed) so particle positions are deterministic.
  const measurer = useMemo(() => {
    if (typeof document === "undefined") return null;
    const el = document.createElementNS(
      "http://www.w3.org/2000/svg",
      "path",
    );
    el.setAttribute("d", edgePath);
    return el;
  }, [edgePath]);

  const flow = data?.flow ?? 0;
  const isDelegate = data?.kind === "delegate";
  const isRevision = data?.kind === "revision";
  const active = flow > 0;
  const enter = data?.enterOpacity ?? 1;

  const total = measurer?.getTotalLength() ?? 0;
  const particles =
    active && enter > 0.99 && total > 0
      ? particleFractions(frame, 3, PARTICLE_PERIOD).map((f) => {
          const pt = measurer!.getPointAtLength(f * total);
          // Fade each particle in/out at the path ends so they don't pop.
          const edge = Math.min(f, 1 - f);
          const opacity = Math.min(1, edge / 0.12);
          return { x: pt.x, y: pt.y, opacity };
        })
      : [];

  const baseOpacity = active ? 1 : isDelegate || isRevision ? 0.45 : 0.6;

  return (
    <>
      <BaseEdge
        path={edgePath}
        style={{
          ...style,
          stroke: active ? "var(--primary)" : "var(--muted-foreground)",
          strokeWidth: 2,
          opacity: baseOpacity * enter,
          strokeDasharray: isRevision ? "2 4" : isDelegate ? "5 4" : undefined,
        }}
      />
      {particles.map((p, i) => (
        <circle
          key={i}
          cx={p.x}
          cy={p.y}
          r={3}
          fill="var(--primary)"
          opacity={p.opacity}
        />
      ))}
    </>
  );
}
