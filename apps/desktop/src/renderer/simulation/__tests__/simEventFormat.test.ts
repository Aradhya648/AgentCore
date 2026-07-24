import { formatSimEventSummary } from "@/simulation/simEventFormat";
import { describe, expect, it } from "vitest";

describe("formatSimEventSummary", () => {
  it("formats tick lifecycle events", () => {
    expect(
      formatSimEventSummary("sim.tick_started", {
        run_id: "r1",
        tick: 3,
        hour: 10,
      }).summary,
    ).toBe("Tick 3 开始 · 10:00");

    expect(
      formatSimEventSummary("sim.tick_ended", {
        run_id: "r1",
        tick: 3,
        hour: 10,
        agent_count: 10,
      }).summary,
    ).toBe("Tick 3 结束 · 10 位居民");
  });

  it("formats agent action and state", () => {
    const action = formatSimEventSummary("sim.agent_action", {
      run_id: "r1",
      tick: 1,
      action: {
        agent_id: "lin",
        action: "move_to",
        thought: "去市场",
        success: true,
        detail: "",
      },
    });
    expect(action.agentId).toBe("lin");
    expect(action.summary).toContain("去市场");

    const state = formatSimEventSummary("sim.agent_state", {
      run_id: "r1",
      tick: 1,
      state: {
        agent_id: "liu",
        name: "刘警官",
        role: "民警",
        location: "广场",
        position: { x: 0, y: 0, z: 0 },
        activity: "巡逻",
        mood: 0,
        goal: "",
        last_thought: "",
      },
    });
    expect(state.agentId).toBe("liu");
    expect(state.summary).toContain("广场");
  });
});
