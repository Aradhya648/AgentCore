import { AgentNode } from "@/components/graph/AgentNode";
import { EndpointNode } from "@/components/graph/EndpointNode";
import type { NodeProps } from "@xyflow/react";
import { useCurrentFrame } from "remotion";
import { entranceStyle, flashShadow, pulseOpacity } from "../motion/primitives";

/*
 * Frame-driven wrappers around the REAL AgentNode / EndpointNode. The inner
 * component renders pixel-identically; the wrapper div re-applies the motions
 * styles.css neutralized — staggered entrance, running pulse, terminal flash —
 * from useCurrentFrame. Motion schedule rides on the node data under `_*` keys
 * (the inner components ignore unknown data keys).
 */

interface MotionFields {
  _enterFrame?: number;
  _terminalFrame?: number | null;
  _ok?: boolean;
  /** Promo stills only: light up a running node with an energy halo (see below). */
  _glow?: boolean;
  status?: string;
}

/* Promo-only energy halo behind a running node so the live team "lights up" against
 * the calm completed/pending nodes — amplifies the real running state for marketing
 * stills (instant focal hierarchy + "alive" read). Alpha rides color-mix on the
 * semantic token (no hardcoded color). Gated by data._glow, which the film never
 * sets, so the video renders pixel-identically. */
const PROMO_RUNNING_GLOW =
  "0 0 28px -2px color-mix(in oklab, var(--primary) 42%, transparent), 0 0 10px -1px color-mix(in oklab, var(--primary) 60%, transparent)";

function useMotionStyle(data: MotionFields): React.CSSProperties {
  const frame = useCurrentFrame();
  const entrance = entranceStyle(frame, data._enterFrame ?? 0);
  const pulse = pulseOpacity(frame, data.status === "running");
  const flash = flashShadow(frame, data._terminalFrame ?? null, data._ok ?? true);
  const glow =
    data._glow && data.status === "running" ? PROMO_RUNNING_GLOW : null;
  const boxShadow = glow
    ? flash === "none"
      ? glow
      : `${glow}, ${flash}`
    : flash;
  return {
    opacity: entrance.opacity * pulse,
    transform: entrance.transform,
    boxShadow,
    borderRadius: 12,
    willChange: "opacity, transform",
  };
}

export function PromoAgentNode(props: NodeProps) {
  const style = useMotionStyle(props.data as MotionFields);
  return (
    <div style={style}>
      <AgentNode {...props} />
    </div>
  );
}

export function PromoEndpointNode(props: NodeProps) {
  const style = useMotionStyle(props.data as MotionFields);
  return (
    <div style={style}>
      <EndpointNode {...props} />
    </div>
  );
}
