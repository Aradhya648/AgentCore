import {
  createInitialSimProjection,
  foldSimulationEvent,
} from "@/simulation/foldSimulation";
import { REGION_POSITIONS } from "@/simulation/regionPositions";
import contract from "@agentcore/protocol-conformance/fixtures/simulation-region-positions.json";
import { describe, expect, it } from "vitest";

describe("region position contract", () => {
  it("matches protocol-conformance fixture", () => {
    expect(REGION_POSITIONS).toEqual(contract.regions);
  });
});

describe("foldSimulationEvent", () => {
  it("moves NPC via sim.agent_state position (authoritative)", () => {
    const projected = foldSimulationEvent(createInitialSimProjection(), {
      type: "sim.agent_state",
      timestamp: "2026-01-01T00:00:00.000Z",
      payload: {
        run_id: "run-1",
        tick: 1,
        state: {
          agent_id: "lin",
          name: "林小梅",
          role: "面包师",
          location: "市场",
          position: { x: 36, y: 0, z: 0 },
          activity: "赶路",
          mood: 0,
          goal: "",
          last_thought: "",
        },
      },
    });

    expect(projected.navTargets.lin).toEqual({ x: 36, y: 0, z: 0 });
  });

  it("records decision summary from sim.agent_action", () => {
    const projected = foldSimulationEvent(createInitialSimProjection(), {
      type: "sim.agent_action",
      timestamp: "2026-01-01T00:00:00.001Z",
      payload: {
        run_id: "run-1",
        tick: 1,
        action: {
          agent_id: "lin",
          action: "move_to",
          thought: "得赶紧去市场进原料。",
          tool_name: null,
          tool_args: { destination: "市场", reason: "进面粉" },
          success: true,
          detail: "",
        },
      },
    });

    expect(projected.decisions[0]?.summary).toBe("得赶紧去市场进原料。");
    expect(projected.decisions[0]?.location).toBe("市场");
    expect(projected.decisions[0]?.actionType).toBe("move_to");
    expect(
      projected.tickEvents.some((e) => e.type === "sim.agent_action"),
    ).toBe(true);
  });

  it("stores active interaction from sim.interaction", () => {
    const projected = foldSimulationEvent(createInitialSimProjection(), {
      type: "sim.interaction",
      timestamp: "2026-01-01T00:00:00.002Z",
      payload: {
        run_id: "run-1",
        tick: 2,
        interaction: {
          request_id: "ix-1",
          kind: "conversation",
          status: "completed",
          initiator_id: "lin",
          target_id: "liu",
          summary: "林与刘聊了几句",
          transcript: [
            {
              speaker_id: "lin",
              speaker_name: "林小梅",
              text: "今天面粉涨价了吗？",
              round: 0,
            },
          ],
        },
      },
    });

    const active = projected.activeInteractions["ix-1"];
    expect(active?.kind).toBe("conversation");
    expect(active?.initiatorId).toBe("lin");
    expect(projected.tickEvents[0]?.interaction?.kind).toBe("conversation");
  });

  it("applies inline snapshot from sim.tick_frame", () => {
    const projected = foldSimulationEvent(createInitialSimProjection(), {
      type: "sim.tick_frame",
      timestamp: "2026-01-01T00:00:00.003Z",
      payload: {
        run_id: "run-1",
        tick_number: 1,
        snapshot: {
          tick: 1,
          hour: 9,
          agents: {
            lin: {
              agent_id: "lin",
              name: "林小梅",
              role: "面包师",
              location: "市场",
              position: { x: 36, y: 0, z: 0 },
              activity: "赶路",
              mood: 0,
              goal: "",
              last_thought: "",
            },
          },
          event_log: [],
        },
      },
    });

    expect(projected.navTargets.lin).toEqual({
      x: 36,
      y: 0,
      z: 0,
    });
    expect(projected.tickCache[1]?.agents?.lin?.location).toBe("市场");
    expect(projected.tickEvents).toHaveLength(0);
  });

  it("updates world modifiers and timeline from sim.world_event", () => {
    const projected = foldSimulationEvent(createInitialSimProjection(), {
      type: "sim.world_event",
      timestamp: "2026-01-01T00:00:00.004Z",
      payload: {
        run_id: "run-1",
        tick: 3,
        event: {
          event_id: "wx-1",
          kind: "daily",
          event_type: "market_open",
          title: "市场开市",
          description: "商贩开始摆摊。",
          tick_started: 3,
          duration_ticks: 4,
          source: "scheduler",
        },
        modifiers: {
          market_price_multiplier: 1.2,
          storm_active: false,
          festival_active: false,
          square_attraction_boost: 0,
        },
      },
    });

    expect(projected.worldModifiers).toEqual({
      market_price_multiplier: 1.2,
      storm_active: false,
      festival_active: false,
      square_attraction_boost: 0,
    });

    expect(projected.tickEvents[0]?.type).toBe("sim.world_event");
    expect(projected.tickEvents[0]?.summary).toBe("市场开市");
    expect(projected.tickEvents[0]?.worldEvent?.event_type).toBe("market_open");
  });
});
