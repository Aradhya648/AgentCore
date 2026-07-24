/**
 * 棘轮：live 首轮帧（辩手发言前）带 opening → fold sticky；后续帧不回退。
 */
import { foldToProjectedTurn } from "@/protocol/conformanceFold";
import { loadFixtures } from "@agentcore/protocol-conformance";
import { describe, expect, it } from "vitest";

describe("live opening from first debate_round_started (fixture)", () => {
  it("roundtable: opening visible at first round_started frame, sticky through later frames", () => {
    const fixture = loadFixtures().find(
      (f) => f.name === "multi_agent_roundtable_rounds",
    );
    expect(fixture).toBeTruthy();
    if (!fixture) return;

    const firstStarted = fixture.events.findIndex(
      (e) => e.type === "debate_round_started",
    );
    expect(firstStarted).toBeGreaterThanOrEqual(0);
    // 含首轮 debate_round_started，尚无辩手 run_started
    const early = foldToProjectedTurn(
      fixture.events.slice(0, firstStarted + 1),
    );
    expect(early.debateOpening).toBe("圆桌开场：先问 AI 治理的风险从何而来。");

    const mid = foldToProjectedTurn(fixture.events.slice(0, firstStarted + 12));
    const full = foldToProjectedTurn(fixture.events);
    expect(mid.debateOpening).toBe(early.debateOpening);
    expect(full.debateOpening).toBe(early.debateOpening);

    // 第 2 轮 started 的 opening 为空，不得覆盖
    const secondStarted = fixture.events.findIndex(
      (e, i) => i > firstStarted && e.type === "debate_round_started",
    );
    expect(secondStarted).toBeGreaterThan(firstStarted);
    expect(
      (fixture.events[secondStarted].payload as { opening?: string }).opening ??
        "",
    ).toBe("");
  });

  it("multi_agent_debate: live sticky matches settled debate.opening", () => {
    const fixture = loadFixtures().find((f) => f.name === "multi_agent_debate");
    expect(fixture).toBeTruthy();
    if (!fixture) return;
    const projected = foldToProjectedTurn(fixture.events);
    expect(projected.debateOpening).toBe(
      "这场要定的是该不该上方案 A，先从最要害的成本与收益切入。",
    );
    expect(projected.debate?.opening).toBe(projected.debateOpening);
  });
});
