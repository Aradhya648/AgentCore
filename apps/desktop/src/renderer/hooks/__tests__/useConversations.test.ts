import {
  bumpConversationCache,
  getConversations,
  patchConversationCache,
  removeConversationFromCache,
  restoreConversationCache,
  upsertConversationFront,
} from "@/hooks/useConversations";
import { queryClient } from "@/lib/queryClient";
import { conversationKeys } from "@/lib/queryKeys";
import {
  TITLE_MAX_CHARS,
  provisionalConversationTitle,
} from "@/services/conversations";
import type { Conversation } from "@/stores/conversation";
import { beforeEach, describe, expect, it } from "vitest";

const mk = (
  id: string,
  updatedAt = "2020-01-01T00:00:00.000Z",
): Conversation => ({
  id,
  title: id.toUpperCase(),
  updatedAt,
  messageCount: 0,
  lastMessagePreview: null,
});

function seed(conversations: Conversation[]): void {
  queryClient.setQueryData(conversationKeys.grouped, {
    folders: [],
    conversations,
  });
}

beforeEach(() => {
  queryClient.clear();
});

// The optimistic conversation-list logic that used to live in the zustand store
// now drives the React Query cache through these imperative helpers (used by the
// SSE turn pipeline and the composer, which run outside React).
describe("conversation list cache helpers", () => {
  it("getConversations returns empty when the cache is cold", () => {
    expect(getConversations()).toEqual([]);
  });

  describe("upsertConversationFront", () => {
    it("prepends a new conversation", () => {
      seed([mk("a")]);
      upsertConversationFront(mk("b"));
      expect(getConversations().map((c) => c.id)).toEqual(["b", "a"]);
    });

    it("moves an existing conversation to the front (deduped)", () => {
      seed([mk("a"), mk("b")]);
      upsertConversationFront(mk("b"));
      expect(getConversations().map((c) => c.id)).toEqual(["b", "a"]);
    });
  });

  describe("removeConversationFromCache", () => {
    it("drops the matching conversation", () => {
      seed([mk("a"), mk("b")]);
      removeConversationFromCache("a");
      expect(getConversations().map((c) => c.id)).toEqual(["b"]);
    });
  });

  describe("patchConversationCache", () => {
    it("shallow-merges a patch onto one conversation", () => {
      seed([mk("a")]);
      patchConversationCache("a", { title: "新标题", folderId: "f1" });
      const [conv] = getConversations();
      expect(conv.title).toBe("新标题");
      expect(conv.folderId).toBe("f1");
    });

    it("is a no-op for an unknown id", () => {
      seed([mk("a")]);
      patchConversationCache("missing", { title: "x" });
      expect(getConversations()[0].title).toBe("A");
    });
  });

  describe("bumpConversationCache", () => {
    it("moves the conversation to the front and refreshes updatedAt", () => {
      seed([mk("a"), mk("b")]);
      bumpConversationCache("b");
      const list = getConversations();
      expect(list.map((c) => c.id)).toEqual(["b", "a"]);
      expect(Date.parse(list[0].updatedAt)).toBeGreaterThan(
        Date.parse("2020-01-01T00:00:00.000Z"),
      );
    });

    it("is a no-op when the id is not in the list", () => {
      seed([mk("a")]);
      bumpConversationCache("missing");
      expect(getConversations().map((c) => c.id)).toEqual(["a"]);
    });
  });

  describe("restoreConversationCache", () => {
    it("undoes a bump, restoring original position and updatedAt", () => {
      seed([
        mk("a", "2020-01-03T00:00:00.000Z"),
        mk("b", "2020-01-02T00:00:00.000Z"),
        mk("c", "2020-01-01T00:00:00.000Z"),
      ]);

      bumpConversationCache("c");
      expect(getConversations().map((x) => x.id)).toEqual(["c", "a", "b"]);

      restoreConversationCache("c", 2, "2020-01-01T00:00:00.000Z");
      expect(getConversations().map((x) => x.id)).toEqual(["a", "b", "c"]);
      expect(getConversations()[2].updatedAt).toBe("2020-01-01T00:00:00.000Z");
    });
  });
});

describe("provisionalConversationTitle", () => {
  it("returns the trimmed message when within TITLE_MAX_CHARS", () => {
    expect(provisionalConversationTitle("  帮我写周报  ")).toBe("帮我写周报");
  });

  it("truncates to TITLE_MAX_CHARS with ellipsis", () => {
    const long = "题".repeat(TITLE_MAX_CHARS + 8);
    expect(provisionalConversationTitle(long)).toBe(
      `${"题".repeat(TITLE_MAX_CHARS)}…`,
    );
  });

  it("falls back to 新对话 for blank input", () => {
    expect(provisionalConversationTitle("   ")).toBe("新对话");
  });
});
