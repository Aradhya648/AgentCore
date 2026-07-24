import { groupConversationsByRecency } from "@/pages/conversations/groupByRecency";
import type { Conversation } from "@/stores/conversation";
import { describe, expect, it } from "vitest";

function conv(id: string, updatedAt: string, pinned = false): Conversation {
  return {
    id,
    title: id,
    updatedAt,
    messageCount: 1,
    lastMessagePreview: null,
    pinned,
  };
}

describe("groupConversationsByRecency", () => {
  // Local calendar anchors — avoid UTC/local drift in CI.
  const now = new Date(2026, 6, 16, 15, 0, 0);

  it("puts pinned first as its own group", () => {
    const list = [
      conv("p", new Date(2026, 6, 1, 0, 0, 0).toISOString(), true),
      conv("t", new Date(2026, 6, 16, 10, 0, 0).toISOString()),
    ];
    const groups = groupConversationsByRecency(list, now);
    expect(groups.map((g) => g.id)).toEqual(["pinned", "today"]);
    expect(groups[0].items.map((c) => c.id)).toEqual(["p"]);
  });

  it("buckets today / yesterday / week / earlier", () => {
    const list = [
      conv("today", new Date(2026, 6, 16, 8, 0, 0).toISOString()),
      conv("yest", new Date(2026, 6, 15, 12, 0, 0).toISOString()),
      conv("week", new Date(2026, 6, 13, 12, 0, 0).toISOString()),
      conv("old", new Date(2026, 5, 1, 12, 0, 0).toISOString()),
    ];
    const groups = groupConversationsByRecency(list, now);
    expect(groups.map((g) => g.id)).toEqual([
      "today",
      "yesterday",
      "week",
      "earlier",
    ]);
  });
});
