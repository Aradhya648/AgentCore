import type { Execution } from "@/stores/execution";
import { describe, expect, it } from "vitest";
import {
  PLAN_GRAPH_CAPABILITIES,
  type PlanType,
  actCapabilities,
  defaultTurnDetailView,
  executionGraphCapabilities,
  isMixedActExecution,
  planCapabilities,
  runActCapabilities,
} from "../planCapabilities";

const ALL_TYPES: PlanType[] = ["single_agent", "multi_agent", "debate"];

describe("planCapabilities", () => {
  it("covers every PlanType exactly once in the table", () => {
    expect(Object.keys(PLAN_GRAPH_CAPABILITIES).sort()).toEqual(
      [...ALL_TYPES].sort(),
    );
  });

  it("null / undefined falls back to single_agent (no graph caps)", () => {
    expect(planCapabilities(null)).toEqual(
      PLAN_GRAPH_CAPABILITIES.single_agent,
    );
    expect(planCapabilities(undefined)).toEqual(
      PLAN_GRAPH_CAPABILITIES.single_agent,
    );
  });

  it("debate shares auditInject with multi_agent (bug fix)", () => {
    expect(planCapabilities("multi_agent").auditInject).toBe(true);
    expect(planCapabilities("debate").auditInject).toBe(true);
    expect(planCapabilities("single_agent").auditInject).toBe(false);
  });

  it("team graph visibility", () => {
    expect(planCapabilities("single_agent").showsTeamGraph).toBe(false);
    expect(planCapabilities("multi_agent").showsTeamGraph).toBe(true);
    expect(planCapabilities("debate").showsTeamGraph).toBe(true);
  });

  it("force-expand debate units only for debate", () => {
    expect(planCapabilities("debate").forceExpandDebateUnits).toBe(true);
    expect(planCapabilities("multi_agent").forceExpandDebateUnits).toBe(false);
    expect(planCapabilities("single_agent").forceExpandDebateUnits).toBe(false);
  });

  it("inline default expanded for team turns", () => {
    expect(planCapabilities("multi_agent").inlineDefaultExpanded).toBe(true);
    expect(planCapabilities("debate").inlineDefaultExpanded).toBe(true);
    expect(planCapabilities("single_agent").inlineDefaultExpanded).toBe(false);
  });

  it("revision badge styles", () => {
    expect(planCapabilities("single_agent").revisionBadgeStyle).toBe("none");
    expect(planCapabilities("multi_agent").revisionBadgeStyle).toBe("hotfix");
    expect(planCapabilities("debate").revisionBadgeStyle).toBe("debate");
  });

  it("runRedirect stays multi_agent-only", () => {
    expect(planCapabilities("multi_agent").runRedirect).toBe(true);
    expect(planCapabilities("debate").runRedirect).toBe(false);
    expect(planCapabilities("single_agent").runRedirect).toBe(false);
  });
});

describe("actCapabilities", () => {
  it("looks up by act kind (幕级取用)", () => {
    expect(actCapabilities("multi_agent")).toEqual(
      PLAN_GRAPH_CAPABILITIES.multi_agent,
    );
    expect(actCapabilities("debate")).toEqual(PLAN_GRAPH_CAPABILITIES.debate);
  });

  it("null / undefined falls back to single_agent", () => {
    expect(actCapabilities(null)).toEqual(PLAN_GRAPH_CAPABILITIES.single_agent);
    expect(actCapabilities(undefined)).toEqual(
      PLAN_GRAPH_CAPABILITIES.single_agent,
    );
  });

  it("matches planCapabilities for the same kind (单幕兼容快捷)", () => {
    expect(actCapabilities("multi_agent")).toEqual(
      planCapabilities("multi_agent"),
    );
    expect(actCapabilities("debate")).toEqual(planCapabilities("debate"));
  });
});

describe("isMixedActExecution / runActCapabilities", () => {
  const mixed = {
    planType: "multi_agent" as const,
    acts: [
      {
        actId: "act-1",
        kind: "multi_agent" as const,
        title: "调研",
        anchorRunId: null,
        authorizedBy: null,
      },
      {
        actId: "act-2",
        kind: "debate" as const,
        title: "辩论",
        anchorRunId: "syn",
      },
    ],
    runs: [
      { id: "syn", actId: "act-1" },
      { id: "mod", actId: "act-2" },
      { id: "pro", actId: "act-2" },
    ],
  } as unknown as Execution;

  it("detects mixed multi_agent + debate acts", () => {
    expect(isMixedActExecution(mixed)).toBe(true);
    expect(
      isMixedActExecution({
        acts: [
          {
            actId: "act-1",
            kind: "debate",
            title: null,
            anchorRunId: null,
            authorizedBy: null,
          },
        ],
      }),
    ).toBe(false);
  });

  it("runRedirect follows the run's act, not host planType", () => {
    expect(runActCapabilities(mixed, "syn").runRedirect).toBe(true);
    expect(runActCapabilities(mixed, "pro").runRedirect).toBe(false);
    expect(runActCapabilities(mixed, "pro").forceExpandDebateUnits).toBe(true);
  });

  it("executionGraphCapabilities unions act caps", () => {
    const caps = executionGraphCapabilities(mixed);
    expect(caps.showsTeamGraph).toBe(true);
    expect(caps.auditInject).toBe(true);
    expect(caps.forceExpandDebateUnits).toBe(true);
    expect(caps.revisionBadgeStyle).toBe("debate");
  });

  it("defaultTurnDetailView: mixed→graph, pure debate→debate", () => {
    expect(defaultTurnDetailView(mixed, true)).toBe("graph");
    expect(
      defaultTurnDetailView(
        {
          acts: [
            {
              actId: "act-1",
              kind: "debate",
              title: null,
              anchorRunId: null,
              authorizedBy: null,
            },
          ],
        },
        true,
      ),
    ).toBe("debate");
  });
});
