import {
  activeInteractionFromResult,
  lastLineForAgent,
  tradeBriefLabel,
  truncateInteractionText,
  voteGovernanceDetails,
} from "@/simulation/interactionModel";
import { describe, expect, it } from "vitest";

describe("interactionModel", () => {
  it("truncates long interaction text", () => {
    expect(truncateInteractionText("短句")).toBe("短句");
    expect(truncateInteractionText("a".repeat(50), 48)).toHaveLength(48);
    expect(truncateInteractionText("a".repeat(50), 48).endsWith("…")).toBe(
      true,
    );
  });

  it("finds last transcript line per agent", () => {
    const transcript = [
      { speaker_id: "lin", speaker_name: "林", text: "你好", round: 0 },
      { speaker_id: "liu", speaker_name: "刘", text: "嗨", round: 1 },
      { speaker_id: "lin", speaker_name: "林", text: "再见", round: 2 },
    ];
    expect(lastLineForAgent(transcript, "lin")).toBe("再见");
    expect(lastLineForAgent(transcript, "liu")).toBe("嗨");
    expect(lastLineForAgent(transcript, "ghost")).toBeNull();
  });

  it("builds active interaction with kind-specific ttl", () => {
    const at = 1_000_000;
    const conversation = activeInteractionFromResult(
      {
        request_id: "c1",
        kind: "conversation",
        status: "completed",
        initiator_id: "lin",
        target_id: "liu",
        summary: "聊了几句",
      },
      3,
      at,
    );
    expect(conversation.expiresAt).toBe(at + 4000);

    const trade = activeInteractionFromResult(
      {
        request_id: "t1",
        kind: "trade",
        status: "completed",
        initiator_id: "lin",
        target_id: "liu",
        summary: "成交",
      },
      3,
      at,
    );
    expect(trade.expiresAt).toBe(at + 3000);
  });

  it("formats trade and vote details", () => {
    const trade = activeInteractionFromResult(
      {
        request_id: "t1",
        kind: "trade",
        status: "completed",
        initiator_id: "lin",
        target_id: "liu",
        summary: "fallback",
        state_changes: {
          inventory_transfers: [
            { from: "liu", to: "lin", item: "面粉", quantity: 2 },
          ],
          money_transfers: [{ from: "lin", to: "liu", amount: 15 }],
        },
      },
      1,
    );
    expect(tradeBriefLabel(trade)).toBe("面粉×2 · 15 币");

    const vote = voteGovernanceDetails({
      governance: {
        motion: "休市一天",
        outcome: "通过",
        yes: 6,
        no: 2,
        abstain: 1,
      },
    });
    expect(vote.motion).toBe("休市一天");
    expect(vote.outcome).toBe("通过");
    expect(vote.yes).toBe(6);
  });
});
