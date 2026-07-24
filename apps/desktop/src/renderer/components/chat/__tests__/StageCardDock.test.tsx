import { StageCardDock } from "@/components/chat/StageCardDock";
import type { InteractionEntry } from "@/stores/interactions";
// @vitest-environment jsdom
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

const byId = new Map<string, InteractionEntry>();

vi.mock("@/stores/conversation", () => ({
  useConversationStore: (
    sel: (s: { currentConversationId: string }) => unknown,
  ) => sel({ currentConversationId: "c1" }),
}));

vi.mock("@/stores/interactions", async () => {
  const actual = await vi.importActual<typeof import("@/stores/interactions")>(
    "@/stores/interactions",
  );
  return {
    ...actual,
    useInteractionStore: (
      sel: (s: { byId: Map<string, InteractionEntry> }) => unknown,
    ) => sel({ byId }),
  };
});

vi.mock("@/components/chat/StageCard", () => ({
  StageCard: ({ entry }: { entry: InteractionEntry }) => (
    <div data-testid={`card-${entry.id}`} data-status={entry.status}>
      {entry.id}
    </div>
  ),
}));

function sc(id: string, status: InteractionEntry["status"]): InteractionEntry {
  return {
    kind: "stage_card",
    id,
    conversationId: "c1",
    messageId: "m1",
    status,
    payload: { motion: "m" },
  };
}

describe("StageCardDock", () => {
  beforeEach(() => {
    byId.clear();
  });

  it("only mounts pending stage cards (no historical resolved/orphaned stack)", () => {
    byId.set("a", sc("a", "pending"));
    byId.set("b", sc("b", "resolved"));
    byId.set("c", sc("c", "orphaned"));
    render(<StageCardDock />);
    expect(screen.getByTestId("stage-card-dock")).toBeTruthy();
    expect(screen.getByTestId("card-a")).toBeTruthy();
    expect(screen.queryByTestId("card-b")).toBeNull();
    expect(screen.queryByTestId("card-c")).toBeNull();
  });

  it("renders nothing when only historical terminal cards exist", () => {
    byId.set("b", sc("b", "resolved"));
    byId.set("c", sc("c", "orphaned"));
    const { container } = render(<StageCardDock />);
    expect(
      container.querySelector('[data-testid="stage-card-dock"]'),
    ).toBeNull();
  });
});
