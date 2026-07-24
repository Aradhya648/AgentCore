import type { Edge, Node } from "@xyflow/react";
import type { DebateState } from "../../core/graph/graphState";
import { GraphStage } from "../../core/graph/GraphStage";
import { STILL_DEFS, type StillDef } from "../data/stills";
import { STILLS_LAYOUT } from "../data/stillsLayout";

/*
 * Renders ONE promo still: a single collaboration scenario frozen at a settled
 * highlight frame (entrance done, running nodes pulsing, particles mid-flow), via
 * the same GraphStage / real AgentNode used by the video. The composition is sized
 * to the scenario's baked ELK bbox + a uniform margin (see Root.tsx), so at frame 0
 * the graph renders at zoom 1 (full-size nodes) tightly cropped — no manual crop,
 * no fit-to-width shrink, no 520px height cap.
 *
 * Frame-0 settled look (the motion primitives are frame-driven):
 *  - `_enterFrame: -100` → entrance fully complete at frame 0 (opacity 1, no rise).
 *  - `_terminalFrame: null` → no one-shot completion flash glow.
 *  - running nodes still read as alive (pulse + AgentNode's own running ring), and
 *    edges into a running node carry `flow: 1` so particles sit mid-path at frame 0.
 */

/** Uniform margin (px, 1x) added around each scenario's bbox — shared with Root. */
export const STILL_FRAME_PAD = 48;

/* The debate 对射 connector's two-way particles are frame-driven (DebateConnector),
 * and at frame 0 both streams meet at the line's midpoint where the end-fade zeroes
 * them out — i.e. frame 0 is the one beat where the 对射 vanishes. A <Still> renders
 * Remotion frame 0, so the standalone debate still must drive the connector at a
 * representative beat to show the real two-way exchange (the film and AppShellStill's
 * frame-240 freeze already do). Only DebateConnector reads this prop; nodes/edges
 * render via their own useCurrentFrame()=0, so this is isolated to the 对射 overlay.
 * 6 ⇒ phase 1/6 ⇒ 3 evenly-spaced, fully-visible dots per direction (none on the
 * end-fade), reading as a live firing axis. */
const DEBATE_CONNECTOR_FRAME = 6;

/* Promo ambient depth (stills only): a soft primary haze centered on the graph that
 * bleeds into the 4:3 letterbox, turning the flat dot-grid whitespace into premium
 * depth and pulling the eye to the team. Rendered BELOW the graph. Token-only color
 * via color-mix (no hardcoded value). */
export function AmbientGlow() {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        background:
          "radial-gradient(ellipse 70% 58% at 50% 50%, color-mix(in oklab, var(--primary) 9%, transparent), transparent 70%)",
      }}
    />
  );
}

/* Subtle edge vignette rendered ABOVE the graph (pointer-none) to seat the scene
 * with a touch of cinematic falloff. Kept faint so node text stays crisp. */
export function AmbientVignette() {
  return (
    <div
      style={{
        position: "absolute",
        inset: 0,
        pointerEvents: "none",
        background:
          "radial-gradient(ellipse 92% 92% at 50% 50%, transparent 56%, color-mix(in oklab, var(--foreground) 7%, transparent))",
      }}
    />
  );
}

/** Unified promo still ratio (product decision): landscape diagrams are framed to
 * 4:3. Each graph stays at native scale (zoom 1, nodes pixel-identical) and is
 * centered by GraphStage in the smallest box of the target ratio that holds it +
 * STILL_FRAME_PAD; graphs that don't match the ratio gain balanced dot-grid
 * letterbox rather than each still keeping its own bbox-tight ratio. */
export const STILL_TARGET_RATIO = 4 / 3;
/** Portrait ratio for top-down (mobile) variants — the 4:3 set's mirror, so the
 * tall panorama stacks vertically and stays legible shrunk to a phone width. */
export const STILL_PORTRAIT_RATIO = 3 / 4;

/** Frame ratio for a still: an explicit `def.ratio` wins; else top-down ("tree")
 * flows are framed portrait and the rest landscape (4:3). Shared by Root and
 * StillScene so both pick the same ratio. */
export function stillRatio(def: { layout: string; ratio?: number }): number {
  return (
    def.ratio ??
    (def.layout === "tree" ? STILL_PORTRAIT_RATIO : STILL_TARGET_RATIO)
  );
}

/** Smallest `ratio` box that holds a `graphW × graphH` bbox plus STILL_FRAME_PAD of
 * breathing room; the short axis is extended to hit the ratio. Used by both this
 * scene (GraphStage box) and Root (the <Still> dimensions) so they stay in lockstep. */
export function stillFrameSize(
  graphW: number,
  graphH: number,
  ratio: number = STILL_TARGET_RATIO,
): { width: number; height: number } {
  const cw = Math.ceil(graphW) + STILL_FRAME_PAD;
  const ch = Math.ceil(graphH) + STILL_FRAME_PAD;
  if (cw / ch < ratio) {
    return { width: Math.ceil(ch * ratio), height: ch };
  }
  return { width: cw, height: Math.ceil(cw / ratio) };
}

const DEF_BY_ID = new Map<string, StillDef>(STILL_DEFS.map((d) => [d.id, d]));

/** Debate 对射 connector from the two stance nodes' baked positions (cx between
 * them, mid-card y), mirroring graphState's DEMO connector geometry. Drawn only
 * when the debate is actually live (a stance node running) — a pending review pair
 * (e.g. in the panorama, where the debate is a downstream wave) shows the banded
 * 正/反 nodes without a firing connector. */
function buildDebate(
  def: StillDef,
  positions: Record<string, { x: number; y: number }>,
): DebateState | null {
  const stance = def.nodes.filter(
    (n) => (n.data as { stance?: string }).stance != null,
  );
  if (stance.length < 2) return null;
  const live = stance.some((n) => (n.data.status as string) === "running");
  if (!live) return null;
  const pts = stance.map((n) => positions[n.id]).filter(Boolean);
  // NODE_WIDTH 210 → center x = x + 105; +66 lands on the card's vertical mid-band.
  if (def.layout === "tree") {
    // Top-down: debaters sit in a row → horizontal 对射 axis across their mid-band.
    const sorted = [...pts].sort((a, b) => a.x - b.x);
    const left = sorted[0];
    const right = sorted[sorted.length - 1];
    const cy = left.y + 66;
    return { x1: left.x + 105, y1: cy, x2: right.x + 105, y2: cy, active: true };
  }
  // leftright: debaters stack in a column → vertical axis.
  const sorted = [...pts].sort((a, b) => a.y - b.y);
  const top = sorted[0];
  const bot = sorted[sorted.length - 1];
  const cx = top.x + 105;
  return { x1: cx, y1: top.y + 66, x2: cx, y2: bot.y + 66, active: true };
}

export function StillScene({ scenarioId }: { scenarioId: string }) {
  const def = DEF_BY_ID.get(scenarioId);
  const layout = STILLS_LAYOUT[scenarioId];
  if (!def || !layout) {
    throw new Error(`StillScene: unknown scenarioId "${scenarioId}"`);
  }

  const handleDirection = def.layout === "tree" ? "vertical" : "horizontal";
  const statusById = new Map(
    def.nodes.map((n) => [n.id, n.data.status as string]),
  );

  const nodes: Node[] = def.nodes.map((n) => {
    const status = n.data.status as string;
    return {
      id: n.id,
      type: n.type,
      position: layout.positions[n.id] ?? { x: 0, y: 0 },
      data: {
        ...n.data,
        status,
        isAnimating: status === "running",
        handleDirection,
        _enterFrame: -100,
        _terminalFrame: null,
        _ok: true,
        _glow: true,
      },
    } as Node;
  });

  const edges: Edge[] = def.edges.map((e) => ({
    id: e.id,
    source: e.source,
    target: e.target,
    type: "flow",
    data: {
      flow: statusById.get(e.target) === "running" ? 1 : 0,
      kind: e.kind,
      enterOpacity: 1,
    },
  }));

  const debate = buildDebate(def, layout.positions);
  const { width: boxWidth, height: boxHeight } = stillFrameSize(
    layout.width,
    layout.height,
    stillRatio(def),
  );

  return (
    <div className="relative h-full w-full overflow-hidden bg-background">
      <AmbientGlow />
      <GraphStage
        nodes={nodes}
        edges={edges}
        debate={debate}
        frame={DEBATE_CONNECTOR_FRAME}
        cinematic
        boxWidth={boxWidth}
        boxHeight={boxHeight}
        graphW={layout.width}
        graphH={layout.height}
        padX={STILL_FRAME_PAD}
        padY={STILL_FRAME_PAD}
        showBackground
      />
      <AmbientVignette />
    </div>
  );
}
