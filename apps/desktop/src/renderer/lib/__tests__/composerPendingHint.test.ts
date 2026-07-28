import { useInteractionStore } from "@/stores/interactions";
import { usePausedTurnStore } from "@/stores/pausedTurns";
// @vitest-environment jsdom
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  COMPOSER_PENDING_HINT,
  COMPOSER_PENDING_SEND_CONFIRM,
  ackSendDespitePending,
  confirmSendDespitePendingIfNeeded,
  conversationHasPendingDecision,
  resetSendDespitePendingAcks,
  shouldConfirmSendDespitePending,
} from "../composerPendingHint";

const CID = "conv_pending_hint";

beforeEach(() => {
  resetSendDespitePendingAcks();
  usePausedTurnStore.getState().clear();
  useInteractionStore.getState().clear();
  vi.restoreAllMocks();
});

describe("composerPendingHint", () => {
  it("exposes short zh copy", () => {
    expect(COMPOSER_PENDING_HINT).toContain("待你确认");
    expect(COMPOSER_PENDING_SEND_CONFIRM).toContain("确定继续");
  });

  it("detects pausedTurns for the conversation", () => {
    expect(conversationHasPendingDecision(CID)).toBe(false);
    usePausedTurnStore.getState().addLiveResume({
      messageId: "m1",
      conversationId: CID,
      checkpointId: "cp1",
      kind: "team_preview",
      userMessage: "开工",
      userMessageId: "u1",
      steps: [],
      pending: [],
      workers: [],
      tools: [],
      primitive: "delegate",
      motion: "",
      form: "",
      sides: [],
      maxRounds: 0,
      thorough: true,
      offerResearchFirst: false,
      researchFirstRecommended: false,
      question: "",
      context: "",
      assumptions: [],
      questions: [],
      styleOptions: [],
      formatOptions: [],
      intent: "kickoff",
      origin: "server",
    });
    expect(conversationHasPendingDecision(CID)).toBe(true);
    expect(conversationHasPendingDecision("other")).toBe(false);
  });

  it("detects pending approval interactions", () => {
    useInteractionStore.getState().hydratePending(CID, [
      {
        kind: "approval",
        id: "a1",
        messageId: "m1",
        payload: { approval_id: "a1", tool_name: "bash" },
      },
    ]);
    expect(conversationHasPendingDecision(CID)).toBe(true);
  });

  it("session ack suppresses further confirms", () => {
    usePausedTurnStore.getState().addLiveResume({
      messageId: "m1",
      conversationId: CID,
      checkpointId: "cp1",
      kind: "ask_user",
      userMessage: "问",
      userMessageId: "u1",
      steps: [],
      pending: [],
      workers: [],
      tools: [],
      primitive: "delegate",
      motion: "",
      form: "",
      sides: [],
      maxRounds: 0,
      thorough: true,
      offerResearchFirst: false,
      researchFirstRecommended: false,
      question: "q",
      context: "",
      assumptions: [],
      questions: [],
      styleOptions: [],
      formatOptions: [],
      intent: "decision",
      origin: "server",
    });
    expect(shouldConfirmSendDespitePending(CID)).toBe(true);
    ackSendDespitePending(CID);
    expect(shouldConfirmSendDespitePending(CID)).toBe(false);
  });

  it("confirmSendDespitePendingIfNeeded: skip while generating; confirm once", () => {
    usePausedTurnStore.getState().addLiveResume({
      messageId: "m1",
      conversationId: CID,
      checkpointId: "cp1",
      kind: "plan_review",
      userMessage: "计划",
      userMessageId: "u1",
      steps: [],
      pending: [],
      workers: [],
      tools: [],
      primitive: "delegate",
      motion: "",
      form: "",
      sides: [],
      maxRounds: 0,
      thorough: true,
      offerResearchFirst: false,
      researchFirstRecommended: false,
      question: "",
      context: "",
      assumptions: [],
      questions: [],
      styleOptions: [],
      formatOptions: [],
      intent: "kickoff",
      origin: "server",
    });

    expect(confirmSendDespitePendingIfNeeded(CID, true)).toBe(true);

    const confirm = vi.spyOn(window, "confirm").mockReturnValue(false);
    expect(confirmSendDespitePendingIfNeeded(CID, false)).toBe(false);
    expect(confirm).toHaveBeenCalledWith(COMPOSER_PENDING_SEND_CONFIRM);

    confirm.mockReturnValue(true);
    expect(confirmSendDespitePendingIfNeeded(CID, false)).toBe(true);
    expect(confirmSendDespitePendingIfNeeded(CID, false)).toBe(true);
    expect(confirm).toHaveBeenCalledTimes(2);
  });
});
