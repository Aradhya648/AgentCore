import { describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: { getPath: () => "/tmp/local-store-test" },
  ipcMain: { handle: vi.fn() },
}));

import {
  LOCAL_STORE_MAX_BYTES,
  LOCAL_STORE_MAX_CONVERSATIONS,
  type LocalStoreConversationMeta,
} from "@shared/local-store-contract";
import { evictLocalStoreIndex } from "../local-store";

function row(
  id: string,
  openedAt: number,
  byteSize: number,
): LocalStoreConversationMeta {
  return {
    id,
    title: id,
    updatedAt: new Date(openedAt).toISOString(),
    messageCount: 1,
    lastMessagePreview: null,
    openedAt,
    byteSize,
  };
}

describe("evictLocalStoreIndex (N4-A)", () => {
  it("keeps at most 20 newest-opened conversations", () => {
    const conversations = Array.from({ length: 25 }, (_, i) =>
      row(`c${i}`, i * 1000, 100),
    );
    const { kept, evictedIds } = evictLocalStoreIndex(
      conversations,
      LOCAL_STORE_MAX_CONVERSATIONS,
      LOCAL_STORE_MAX_BYTES,
    );
    expect(kept).toHaveLength(20);
    expect(evictedIds).toHaveLength(5);
    expect(kept.map((c) => c.id)).toEqual(
      Array.from({ length: 20 }, (_, i) => `c${24 - i}`),
    );
  });

  it("evicts oldest when byte budget would exceed ~50 MiB", () => {
    const big = Math.floor(LOCAL_STORE_MAX_BYTES / 2) + 1;
    const conversations = [
      row("old", 1, big),
      row("mid", 2, big),
      row("new", 3, big),
    ];
    const { kept, evictedIds } = evictLocalStoreIndex(
      conversations,
      LOCAL_STORE_MAX_CONVERSATIONS,
      LOCAL_STORE_MAX_BYTES,
    );
    // Each payload is just over half the budget → only the newest fits.
    expect(kept.map((c) => c.id)).toEqual(["new"]);
    expect(evictedIds.sort()).toEqual(["mid", "old"]);
  });
});
