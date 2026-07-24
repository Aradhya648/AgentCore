// @vitest-environment jsdom
import { useInteractionStore } from "@/stores/interactions";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { StageCardTrace } from "../HotDecisionTrace";

describe("StageCardTrace", () => {
  beforeEach(() => {
    useInteractionStore.setState({ byId: new Map() });
  });

  afterEach(() => {
    cleanup();
  });

  it("renders resolved start_debate outcome", () => {
    const store = useInteractionStore.getState();
    store.upsertRequired({
      kind: "stage_card",
      conversationId: "c1",
      messageId: "m1",
      payload: { stage_card_id: "sc1", motion: "命题" },
    });
    store.markResolved({
      kind: "stage_card",
      id: "sc1",
      resolution: { decision: "start_debate" },
    });
    render(<StageCardTrace stageCardId="sc1" />);
    expect(screen.getByTestId("stage-card-trace").textContent).toContain(
      "推进卡 · 已开辩",
    );
  });

  it("renders orphaned outcome", () => {
    const store = useInteractionStore.getState();
    store.upsertRequired({
      kind: "stage_card",
      conversationId: "c1",
      messageId: "m1",
      payload: { stage_card_id: "sc2", motion: "命题" },
    });
    store.markOrphaned("sc2", { kind: "stage_card" });
    render(<StageCardTrace stageCardId="sc2" />);
    expect(screen.getByTestId("stage-card-trace").textContent).toContain(
      "推进卡 · 已失效",
    );
  });

  it("hides pending (Dock owns the card)", () => {
    useInteractionStore.getState().upsertRequired({
      kind: "stage_card",
      conversationId: "c1",
      messageId: "m1",
      payload: { stage_card_id: "sc3", motion: "命题" },
    });
    const { container } = render(<StageCardTrace stageCardId="sc3" />);
    expect(container.textContent).toBe("");
  });
});
