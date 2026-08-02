/**
 * Canvas Document gate: streaming deltas must reuse per-turn shell projections.
 */
import type { Execution } from "@/stores/execution";
import { describe, expect, it } from "vitest";
import {
  buildCanvasTurnProjections,
  canvasTurnDocumentGateKey,
} from "../canvasTurnProjection";
import { INPUT_ID } from "../constants";
import { buildGraphScene } from "../scene";
import type { TurnLayoutSlice } from "../useGraphLayout";

function minimalExec(output = ""): Execution {
  return {
    id: "e1",
    planType: "multi_agent",
    taskSummary: "并行调研",
    status: "running",
    agents: [
      {
        id: "w1",
        role: "member",
        outputChunks: output ? [output] : [],
        reasoningChunks: [],
        toolCalls: [],
        toolProgress: null,
        toolExecutionLive: null,
        didRework: false,
        currentRunId: "w1",
        thinking: false,
        status: "working",
      },
    ],
    runs: [
      {
        id: "captain",
        agentId: "ceo",
        task: "",
        status: "pending",
        dependsOn: ["w1"],
        outputSummary: null,
        outputFiles: [],
        debrief: null,
        durationMs: null,
        startedAt: null,
        error: null,
        parentRunId: null,
        kind: "captain",
        role: null,
        model: null,
        usage: null,
        cost: null,
        stance: null,
        group: null,
        round: 0,
        sideKey: null,
        continuesRunId: null,
        continuationIndex: 0,
        replacesRunId: null,
        revised: null,
        checkpoint: null,
        receivedContext: [],
        escalations: [],
        process: [],
      },
      {
        id: "w1",
        agentId: "w1",
        task: "调研",
        status: "running",
        dependsOn: [],
        outputSummary: null,
        outputFiles: [],
        debrief: null,
        durationMs: null,
        startedAt: 1,
        error: null,
        parentRunId: null,
        kind: "agent",
        role: "member",
        model: null,
        usage: null,
        cost: null,
        stance: null,
        group: null,
        round: 0,
        sideKey: null,
        continuesRunId: null,
        continuationIndex: 0,
        replacesRunId: null,
        revised: null,
        checkpoint: null,
        receivedContext: [],
        escalations: [],
        process: [],
      },
    ],
    progress: { completed: 0, total: 2 },
    acts: [],
    batches: [],
    debate: null,
    debateRounds: [],
    crossExamEnabled: false,
    debateOpening: null,
    debatePretrial: null,
    teamNotes: [],
  };
}

const positions = {
  [INPUT_ID]: { x: 0, y: 0 },
  captain: { x: 0, y: 200 },
  w1: { x: 0, y: 100 },
};

function readySlice(execution: Execution): TurnLayoutSlice {
  const scene = buildGraphScene(execution);
  return {
    positions,
    edges: [
      { id: "in->w1", source: INPUT_ID, target: "w1", kind: "dep" },
      { id: "w1->cap", source: "w1", target: "captain", kind: "dep" },
    ],
    bbox: { width: 400, height: 400 },
    layoutReady: true,
    layoutError: null,
    nodeHeights: {},
    nodeSizes: {},
    groups: [],
    subTeams: [],
    foldInfo: scene.fold,
    scene,
    actCards: [],
  };
}

describe("Canvas Document/Live · delta does not replace shell refs", () => {
  const ctx = {
    collapsedSubtrees: new Set<string>(),
    handleDirection: "vertical" as const,
    edgePathType: "smoothstep" as const,
    layoutKind: "leftright" as const,
    actFocusByTurn: new Map<string, string | null | undefined>(),
  };

  it("gate key stable across output-only deltas", () => {
    const a = minimalExec("hello");
    const b = minimalExec("hello world more tokens");
    const slice = readySlice(a);
    const ka = canvasTurnDocumentGateKey("t1", a, slice, ctx);
    const kb = canvasTurnDocumentGateKey("t1", b, slice, ctx);
    expect(ka).toBe(kb);
  });

  it("buildCanvasTurnProjections reuses prior Map + node refs on delta", () => {
    const a = minimalExec("a");
    const b = minimalExec("a".repeat(200));
    const layouts = { t1: readySlice(a) };
    const gate = canvasTurnDocumentGateKey("t1", a, layouts.t1, ctx);
    const first = buildCanvasTurnProjections(
      [{ turnId: "t1", execution: a }],
      layouts,
      ctx,
    );
    const second = buildCanvasTurnProjections(
      [{ turnId: "t1", execution: b }],
      layouts,
      ctx,
      first,
      gate,
      gate,
    );
    expect(second).toBe(first);
    expect(second.get("t1")).toBe(first.get("t1"));
    expect(second.get("t1")?.layoutNodes).toBe(first.get("t1")?.layoutNodes);
    expect(second.get("t1")?.edges).toBe(first.get("t1")?.edges);
    expect(
      first
        .get("t1")
        ?.layoutNodes.some((n) => n.type === "captain" && n.id === "captain"),
    ).toBe(true);
    const worker = first.get("t1")?.layoutNodes.find((n) => n.id === "w1");
    expect(worker?.data).not.toHaveProperty("outputPreview");
    expect(worker?.data).not.toHaveProperty("status");
  });
});
