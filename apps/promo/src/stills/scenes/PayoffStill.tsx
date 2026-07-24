import type { Edge, Node } from "@xyflow/react";
import { GraphStage } from "../../core/graph/GraphStage";
import { CAPTAIN_ID } from "../../videos/brand-30s/data/demo";
import { buildBrandGraphState } from "../../videos/brand-30s/data/graphSpec";
import { DEMO_LAYOUT } from "../../videos/brand-30s/data/layout";
import { AmbientGlow, AmbientVignette, stillFrameSize, STILL_FRAME_PAD } from "./StillScene";

/*
 * 收束高潮 still — the payoff every other crop is missing: the whole butterfly has
 * delivered (all workers green/settled) and the CEO 汇聚点 is now lit, pulling the
 * team's output in. Reuses the demo graph at a late beat (specs done @390, ruling
 * done @345, debate over) with a captain override that flips the sink to running +
 * a glow, and forces its two inbound edges to flow so particles converge into it.
 *
 * The single glowing node (only the CEO is running) makes the focal point
 * unambiguous: a team finished, the boss is assembling the result. Bare 4:3 like the
 * STILL_DEFS diagrams (same AmbientGlow/Vignette depth), so it slots into the set.
 */

const FROZEN = 404; // just past spec done(390): all workers complete, CEO assembling
const FPS = 30;

export function PayoffStill() {
  const { nodes, edges } = buildBrandGraphState(FROZEN, FPS, {
    captain: {
      status: "running",
      preview: "正在汇总三方产出，裁决并形成最终方案……",
      terminalFrame: null,
    },
  });

  const settled: Node[] = nodes.map((n) => ({
    ...n,
    data: { ...n.data, _enterFrame: -100, _terminalFrame: null, _glow: true },
  }));

  // Converging particles: the demo's edgeFlow has no schedule entry for the sink,
  // so force the captain's inbound edges to flow at the payoff beat.
  const converged: Edge[] = edges.map((e) =>
    e.target === CAPTAIN_ID
      ? { ...e, data: { ...(e.data as Record<string, unknown>), flow: 1, enterOpacity: 1 } }
      : e,
  );

  const { width: boxWidth, height: boxHeight } = stillFrameSize(
    DEMO_LAYOUT.width,
    DEMO_LAYOUT.height,
  );

  return (
    <div className="relative h-full w-full overflow-hidden bg-background">
      <AmbientGlow />
      <GraphStage
        nodes={settled}
        edges={converged}
        debate={null}
        frame={FROZEN}
        boxWidth={boxWidth}
        boxHeight={boxHeight}
        graphW={DEMO_LAYOUT.width}
        graphH={DEMO_LAYOUT.height}
        padX={STILL_FRAME_PAD}
        padY={STILL_FRAME_PAD}
        showBackground
      />
      <AmbientVignette />
    </div>
  );
}
