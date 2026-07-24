import { describe, expect, it } from "vitest";
import {
  deriveInterruptedAfterDecision,
  hasColdGatePending,
  shouldRetainOpenForContinue,
} from "../recoveryFold";

describe("recoveryFold (D2)", () => {
  it("hasColdGatePending is true until matching resolved", () => {
    expect(
      hasColdGatePending([
        {
          kind: "team_preview_required",
          payload: { checkpoint_id: "tp1" },
        },
      ]),
    ).toBe(true);
    expect(
      hasColdGatePending([
        {
          kind: "team_preview_required",
          payload: { checkpoint_id: "tp1" },
        },
        {
          kind: "team_preview_resolved",
          payload: { checkpoint_id: "tp1", decision: "continue" },
        },
      ]),
    ).toBe(false);
  });

  it("deriveInterruptedAfterDecision requires settlement + non-terminal", () => {
    const journal = {
      "0": {
        kind: "team_preview_required",
        payload: { checkpoint_id: "tp1" },
      },
      "1": {
        kind: "team_preview_resolved",
        payload: {
          checkpoint_id: "tp1",
          decision: "continue",
          resume_frame: { frame: { kind: "team_preview" } },
        },
      },
    };
    expect(
      deriveInterruptedAfterDecision({
        conversationId: "c1",
        userMessageId: "u1",
        messageId: "m1",
        finishReason: null,
        journal,
      }),
    ).toMatchObject({
      messageId: "m1",
      settledKind: "team_preview",
      checkpointId: "tp1",
    });
    expect(
      deriveInterruptedAfterDecision({
        conversationId: "c1",
        userMessageId: "u1",
        messageId: "m1",
        finishReason: "end_turn",
        journal,
      }),
    ).toBeNull();
  });

  it("second gate pending suppresses interrupted card but still retains open", () => {
    const journal = {
      "0": {
        kind: "team_preview_resolved",
        payload: { checkpoint_id: "tp1", decision: "continue" },
      },
      "1": {
        kind: "checkpoint_required",
        payload: { checkpoint_id: "cp2" },
      },
    };
    expect(
      deriveInterruptedAfterDecision({
        conversationId: "c1",
        userMessageId: "u1",
        messageId: "m1",
        finishReason: "paused",
        journal,
      }),
    ).toBeNull();
    // Conservative retain: settlement + non-terminal → keep local journal even
    // when a later cold gate is pending (align Python OutboxStore.salvage).
    expect(
      shouldRetainOpenForContinue({ finishReason: "paused", journal }),
    ).toBe(true);
  });

  it("shouldRetainOpenForContinue is true for settled non-terminal, false when terminal", () => {
    const journal = {
      "0": {
        kind: "team_preview_resolved",
        payload: {
          checkpoint_id: "tp1",
          decision: "continue",
          resume_frame: { frame: { kind: "team_preview" } },
        },
      },
    };
    expect(shouldRetainOpenForContinue({ finishReason: null, journal })).toBe(
      true,
    );
    expect(
      shouldRetainOpenForContinue({ finishReason: "paused", journal }),
    ).toBe(true);
    expect(
      shouldRetainOpenForContinue({ finishReason: "end_turn", journal }),
    ).toBe(false);
    expect(
      shouldRetainOpenForContinue({ finishReason: "cancelled", journal: {} }),
    ).toBe(false);
  });
});
