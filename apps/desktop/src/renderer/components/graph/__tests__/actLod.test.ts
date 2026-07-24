/**
 * 幕级 LOD 布局金样（批 R2）——钉死「幕摘要卡链 + 恰好一个聚焦幕展开完整 DAG」：
 * 聚焦幕的 run 有坐标、非聚焦幕降级为一张卡节点、聚焦默认随执行态。ELK 只为聚焦幕
 * 算完整布局（本测试跑真实 elkjs，和 useGraphLayout.relayout 同源）。
 */
import type { Execution, ExecutionAct, RunStatus } from "@/stores/execution";
import { describe, expect, it } from "vitest";
import {
  actCardId,
  computeActLodLayout,
  defaultFocusedActId,
  parseActCardId,
} from "../actLod";
import { buildGraphScene } from "../scene";

interface RunSpec {
  id: string;
  dependsOn?: string[];
  parentRunId?: string | null;
  stance?: "pro" | "con" | null;
  group?: string | null;
  actId?: string;
  status?: RunStatus;
  role?: string;
  durationMs?: number;
}

function mkExec(specs: RunSpec[], status: Execution["status"]): Execution {
  const acts: ExecutionAct[] = [
    {
      actId: "act-1",
      kind: "multi_agent",
      title: "多视角调研",
      anchorRunId: null,
      authorizedBy: null,
    },
    {
      actId: "act-2",
      kind: "debate",
      title: "辩论对抗",
      anchorRunId: "synthesizer",
      authorizedBy: "stage_card",
    },
  ];
  const runs = specs.map((s) => ({
    id: s.id,
    agentId: s.id,
    role: s.role ?? null,
    dependsOn: s.dependsOn ?? [],
    parentRunId: s.parentRunId ?? null,
    continuesRunId: null,
    continuationIndex: 0,
    replacesRunId: null,
    stance: s.stance ?? null,
    group: s.group ?? null,
    round: 0,
    kind: "agent",
    actId: s.actId,
    receivedContext: [],
    status: s.status ?? "completed",
    durationMs: s.durationMs ?? null,
    escalations: [],
    checkpoint: null,
  }));
  return { runs, acts, agents: [], status } as unknown as Execution;
}

const TWO_ACT: RunSpec[] = [
  { id: "lens_0", actId: "act-1", role: "法律" },
  { id: "synthesizer", dependsOn: ["lens_0"], actId: "act-1", role: "汇总" },
  { id: "mod", parentRunId: "synthesizer", actId: "act-2", role: "主持人" },
  {
    id: "mod_r1_pro",
    parentRunId: "mod",
    actId: "act-2",
    stance: "pro",
    group: "debate:debate",
    role: "正方",
  },
  {
    id: "mod_r1_con",
    parentRunId: "mod",
    actId: "act-2",
    stance: "con",
    group: "debate:debate",
    role: "反方",
  },
];

describe("actCardId / parseActCardId", () => {
  it("round-trips an act id and rejects non-cards", () => {
    expect(actCardId("act-2")).toBe("__act__act-2");
    expect(parseActCardId("__act__act-2")).toBe("act-2");
    expect(parseActCardId("mod")).toBeNull();
  });
});

describe("defaultFocusedActId", () => {
  const scene = buildGraphScene(mkExec(TWO_ACT, "completed"));
  const running = buildGraphScene(
    mkExec(
      [
        { id: "lens_0", actId: "act-1", status: "completed" },
        {
          id: "synthesizer",
          dependsOn: ["lens_0"],
          actId: "act-1",
          status: "completed",
        },
        {
          id: "mod",
          parentRunId: "synthesizer",
          actId: "act-2",
          status: "running",
        },
      ],
      "running",
    ),
    { inputId: "__input__" },
  );

  it("completed turn defaults to fully-collapsed (null)", () => {
    expect(defaultFocusedActId(scene, "completed", undefined)).toBeNull();
  });
  it("running turn auto-focuses the active act", () => {
    expect(defaultFocusedActId(running, "running", undefined)).toBe("act-2");
  });
  it("respects an explicit user choice (incl. collapse)", () => {
    expect(defaultFocusedActId(scene, "completed", "act-1")).toBe("act-1");
    expect(defaultFocusedActId(running, "running", null)).toBeNull();
  });
});

describe("computeActLodLayout", () => {
  it("collapsed (focus=null) → one card per act, no run positions", async () => {
    const exec = mkExec(TWO_ACT, "completed");
    const scene = buildGraphScene(exec);
    const lod = await computeActLodLayout(
      exec,
      scene,
      null,
      "leftright",
      "view",
    );
    expect(lod.cards.map((c) => c.actId)).toEqual(["act-1", "act-2"]);
    expect(lod.positions[actCardId("act-1")]).toBeDefined();
    expect(lod.positions[actCardId("act-2")]).toBeDefined();
    expect(lod.positions.lens_0).toBeUndefined();
    expect(lod.positions.mod).toBeUndefined();
    expect(lod.bbox.width).toBeGreaterThan(0);
    expect(lod.bbox.height).toBeGreaterThan(0);
  });

  it("focus=act-2 → act-2 runs laid out, act-1 folded to a card", async () => {
    const exec = mkExec(TWO_ACT, "completed");
    const scene = buildGraphScene(exec);
    const lod = await computeActLodLayout(
      exec,
      scene,
      "act-2",
      "leftright",
      "view",
    );
    // Only the non-focused act keeps a card.
    expect(lod.cards.map((c) => c.actId)).toEqual(["act-1"]);
    expect(lod.focusedActId).toBe("act-2");
    // Focused act runs are positioned (the debate compound members included).
    expect(lod.positions.mod).toBeDefined();
    expect(lod.positions.mod_r1_pro).toBeDefined();
    expect(lod.positions.mod_r1_con).toBeDefined();
    // The folded act renders as a card, not its runs.
    expect(lod.positions[actCardId("act-1")]).toBeDefined();
    expect(lod.positions.lens_0).toBeUndefined();
    expect(lod.positions[actCardId("act-2")]).toBeUndefined();
    // A downgraded act-chain edge links act-1 card → focused act-2 entry.
    expect(lod.edges.some((e) => e.source === actCardId("act-1"))).toBe(true);
  });

  it("focus=act-1 → act-1 runs laid out, act-2 folded to a card", async () => {
    const exec = mkExec(TWO_ACT, "completed");
    const scene = buildGraphScene(exec);
    const lod = await computeActLodLayout(
      exec,
      scene,
      "act-1",
      "leftright",
      "view",
    );
    expect(lod.cards.map((c) => c.actId)).toEqual(["act-2"]);
    expect(lod.positions.lens_0).toBeDefined();
    expect(lod.positions.synthesizer).toBeDefined();
    expect(lod.positions[actCardId("act-2")]).toBeDefined();
    expect(lod.positions.mod).toBeUndefined();
  });
});
