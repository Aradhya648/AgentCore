// REST-shape conformance for the AI Town simulation contract (ST-02). The backend REST
// responses (create/tick/ticks/metrics/manifest/status/inject/patch) are frozen; these
// committed fixtures are the golden shapes. Where the desktop has a real wire→view mapper
// (runFromWire), we fold through it; otherwise we assert the exact fields the contract
// freezes. Type annotations on OpenAPI-backed fixtures also make `pnpm typecheck` fail if
// a schema drifts.
import { runFromWire } from "@/simulation/runModel";
import type { components } from "@agentcore/contract-rest-types";
import type { SimAgentState } from "@agentcore/contract-types";
import restAdvanceTick from "@agentcore/protocol-conformance/fixtures/simulation/rest-advance-tick.json" with {
  type: "json",
};
import restInject from "@agentcore/protocol-conformance/fixtures/simulation/rest-inject.json" with {
  type: "json",
};
import restManifest from "@agentcore/protocol-conformance/fixtures/simulation/rest-manifest.json" with {
  type: "json",
};
import restMetrics from "@agentcore/protocol-conformance/fixtures/simulation/rest-metrics.json" with {
  type: "json",
};
import restPatchAgent from "@agentcore/protocol-conformance/fixtures/simulation/rest-patch-agent.json" with {
  type: "json",
};
import restRunStatus from "@agentcore/protocol-conformance/fixtures/simulation/rest-run-status.json" with {
  type: "json",
};
import restRunSummary from "@agentcore/protocol-conformance/fixtures/simulation/rest-run-summary.json" with {
  type: "json",
};
import restTickFrame from "@agentcore/protocol-conformance/fixtures/simulation/rest-tick-frame.json" with {
  type: "json",
};
import { describe, expect, it } from "vitest";

type SimTickMetrics = components["schemas"]["TickMetrics"];
type SimMetricsResponse = components["schemas"]["SimulationRunMetricsResponse"];

function expectAgentState(state: SimAgentState): void {
  expect(typeof state.agent_id).toBe("string");
  expect(typeof state.name).toBe("string");
  expect(typeof state.role).toBe("string");
  expect(typeof state.location).toBe("string");
  expect(typeof state.position.x).toBe("number");
  expect(typeof state.position.y).toBe("number");
  expect(typeof state.position.z).toBe("number");
  expect(typeof state.mood).toBe("number");
}

function expectTickMetrics(m: SimTickMetrics): void {
  for (const key of [
    "tick",
    "hour",
    "avg_mood",
    "trade_count",
    "trade_total_amount",
    "positive_relation_ratio",
  ] as const) {
    expect(typeof m[key]).toBe("number");
  }
  expect(typeof m.population_by_region).toBe("object");
}

describe("simulation ST-02 conformance · REST shape", () => {
  it("create → SimulationRunSummary folds via runFromWire", () => {
    const view = runFromWire(restRunSummary.response);
    expect(view).toEqual({
      id: "run-conformance",
      scenario: "town",
      tick: 0,
      hour: 0,
      status: "created",
    });
  });

  it("advance tick → AdvanceTickResponse carries a snapshot with clock", () => {
    const { response } = restAdvanceTick;
    expect(response.run_id).toBe("run-conformance");
    expect(typeof response.snapshot.tick).toBe("number");
    expect(typeof response.snapshot.hour).toBe("number");
    expectAgentState(response.snapshot.agents.lin as SimAgentState);
  });

  it("tick frame → SimTickFrameResponse exposes tick_number + snapshot", () => {
    const { response } = restTickFrame;
    expect(response.run_id).toBe("run-conformance");
    expect(response.tick_number).toBe(response.snapshot.tick);
    expect(typeof response.snapshot.hour).toBe("number");
    expect(Object.keys(response.snapshot.agents).length).toBeGreaterThan(0);
    expect(Array.isArray(response.snapshot.event_log)).toBe(true);
  });

  it("pause/resume → SimulationRunStatusResponse shape", () => {
    const { response } = restRunStatus;
    expect(typeof response.run_id).toBe("string");
    expect(typeof response.status).toBe("string");
    expect(typeof response.current_tick).toBe("number");
  });

  it("metrics → SimulationRunMetricsResponse is a TickMetrics series", () => {
    const metrics: SimMetricsResponse = restMetrics.response;
    expect(typeof metrics.run_id).toBe("string");
    expect(metrics.metrics.length).toBeGreaterThan(0);
    for (const m of metrics.metrics) expectTickMetrics(m);
  });

  it("manifest → RunManifest is reproducible experiment descriptor", () => {
    const { manifest } = restManifest.response;
    expect(typeof manifest.manifest_version).toBe("string");
    expect(manifest.scenario).toBe("town");
    expect(typeof manifest.seed).toBe("number");
    expect(typeof manifest.temperature).toBe("number");
    expect(Array.isArray(manifest.personas)).toBe(true);
    expect(manifest.personas.length).toBeGreaterThan(0);
    expect(Array.isArray(manifest.regions)).toBe(true);
    expect(manifest.regions).toContain("市场");
  });

  it("inject → InjectSimulationEventResponse is queued for a future tick", () => {
    const { response } = restInject;
    expect(typeof response.run_id).toBe("string");
    expect(typeof response.event_id).toBe("string");
    expect(typeof response.event_type).toBe("string");
    expect(typeof response.title).toBe("string");
    expect(typeof response.queued_for_tick).toBe("number");
  });

  it("patch agent → PatchSimulationAgentResponse returns updated state", () => {
    const { response } = restPatchAgent;
    expect(response.agent_id).toBe(response.state.agent_id);
    expectAgentState(response.state as SimAgentState);
  });
});
