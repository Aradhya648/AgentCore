import type { Edge, Node } from "@xyflow/react";
import { interpolate, useCurrentFrame, useVideoConfig } from "remotion";
import { mainBox } from "../../../core/chrome/PromoShell";
import { GraphStage } from "../../../core/graph/GraphStage";
import { entranceStyle } from "../../../core/motion/primitives";
import { type Scenario, SCENARIOS } from "../data/scenarios";

/*
 * 24–27s capability montage (scene-local 0–90 @30fps): three 1-second quick cuts
 * of real collaboration shapes — 并行扇出 / 辩论正反 / 嵌套小队 — each a small DAG
 * rendered with the same AgentNode / EndpointNode as the hero graph, animated in
 * per cut. A caption names the pattern; the subtitle ties them together.
 */

const CUT = 30; // 1s per scenario

function buildCut(scenario: Scenario, cutStart: number, frame: number) {
  const enterOf = (i: number) => cutStart + 2 + i * 4;

  const nodes: Node[] = scenario.nodes.map((n, i) => ({
    id: n.id,
    type: n.type,
    position: n.position,
    data: {
      ...n.data,
      _enterFrame: enterOf(i),
      _terminalFrame: null,
      _ok: true,
      handleDirection: "horizontal",
    },
  }));

  const indexById = new Map(scenario.nodes.map((n, i) => [n.id, i]));
  const edges: Edge[] = scenario.edges.map((e) => {
    const appear =
      Math.max(enterOf(indexById.get(e.source) ?? 0), enterOf(indexById.get(e.target) ?? 0)) + 5;
    const enterOpacity = interpolate(frame, [appear - 9, appear], [0, 1], {
      extrapolateLeft: "clamp",
      extrapolateRight: "clamp",
    });
    return {
      id: e.id,
      source: e.source,
      target: e.target,
      type: "flow",
      data: { flow: 0, kind: e.kind, enterOpacity },
    } as Edge;
  });

  return { nodes, edges };
}

export function ScenarioMain() {
  const frame = useCurrentFrame();
  const { width, height } = useVideoConfig();
  const { width: boxWidth, height: boxHeight } = mainBox(width, height);
  const idx = Math.min(SCENARIOS.length - 1, Math.floor(frame / CUT));
  const cutStart = idx * CUT;
  const cutLocal = frame - cutStart;
  const scenario = SCENARIOS[idx];

  const { nodes, edges } = buildCut(scenario, cutStart, frame);

  // Soft fade at each cut's edges so the swap doesn't pop.
  const cutOpacity = interpolate(
    cutLocal,
    [0, 5, CUT - 5, CUT],
    [0, 1, 1, 0],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp" },
  );
  const caption = entranceStyle(frame, cutStart + 2);

  return (
    <div style={{ position: "absolute", inset: 0, opacity: cutOpacity }}>
      <div
        style={{
          position: "absolute",
          top: 40,
          left: 0,
          right: 0,
          display: "flex",
          justifyContent: "center",
          zIndex: 2,
          opacity: caption.opacity,
          transform: caption.transform,
        }}
      >
        <div className="rounded-full bg-accent px-5 py-1.5 text-lg font-medium text-accent-foreground">
          {scenario.label}
        </div>
      </div>
      <GraphStage
        key={scenario.id}
        nodes={nodes}
        edges={edges}
        debate={null}
        frame={frame}
        boxWidth={boxWidth}
        boxHeight={boxHeight}
        graphW={scenario.width}
        graphH={scenario.height}
        showBackground={false}
        padY={220}
      />
    </div>
  );
}
