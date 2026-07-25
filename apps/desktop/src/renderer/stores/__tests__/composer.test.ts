// @vitest-environment jsdom
import { uiGet, uiSet } from "@/lib/uiStorage";
import {
  __reloadComposerDraftsForTests,
  draftKeyFor,
  useComposerDraftStore,
} from "@/stores/composer";
import { useConversationStore } from "@/stores/conversation";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Per-conversation composer drafts (统一输入框草稿): keyed storage + 回填 + the
 * persistence layer (text survives a restart via uiStorage, attachments stay
 * session-only, cap keeps the map bounded).
 *
 * Avoid `vi.resetModules()` + dynamic import of `@/stores/conversation` — the
 * conversation graph hangs under module reset in this package.
 */

const STORAGE_LEAF = "composer-drafts";

function persisted(): Record<string, { value: string; updatedAt: number }> {
  return uiGet(STORAGE_LEAF) ?? {};
}

const attachment = {
  id: "a1",
  key: "file:src:x.ts",
  name: "x.ts",
  path: "src/x.ts",
  text: "content",
  truncated: false,
  kind: "file" as const,
};

beforeEach(() => {
  vi.useRealTimers();
  uiSet(STORAGE_LEAF, undefined);
  useComposerDraftStore.setState({
    drafts: {},
    fillToken: 0,
    dockFlipToken: 0,
  });
  useConversationStore.setState({ currentConversationId: null });
});

afterEach(() => {
  vi.useRealTimers();
});

describe("composer draft store", () => {
  it("keys drafts by conversation and drops emptied entries", () => {
    const s = useComposerDraftStore.getState();

    s.setValue("c1", "给团队的指令");
    s.setValue("c2", "另一条");
    expect(useComposerDraftStore.getState().drafts.c1?.value).toBe(
      "给团队的指令",
    );
    expect(useComposerDraftStore.getState().drafts.c2?.value).toBe("另一条");

    s.setValue("c1", "");
    expect(useComposerDraftStore.getState().drafts.c1).toBeUndefined();
    expect(useComposerDraftStore.getState().drafts.c2?.value).toBe("另一条");
  });

  it("fill appends into the ACTIVE conversation's draft and bumps the focus token", () => {
    useConversationStore.setState({ currentConversationId: "c9" });

    const s = useComposerDraftStore.getState();
    s.setValue("c9", "已有内容");
    s.fill("选项 A");
    expect(useComposerDraftStore.getState().drafts.c9?.value).toBe(
      "已有内容\n选项 A",
    );
    s.fill("整个换掉", "replace");
    expect(useComposerDraftStore.getState().drafts.c9?.value).toBe("整个换掉");
    expect(useComposerDraftStore.getState().fillToken).toBe(2);

    // No active conversation → the draft-chat sentinel key.
    useConversationStore.setState({ currentConversationId: null });
    s.fill("草稿聊天");
    expect(
      useComposerDraftStore.getState().drafts[draftKeyFor(null)]?.value,
    ).toBe("草稿聊天");
  });

  it("persists draft TEXT (debounced) and restores it on reload; attachments stay session-only", () => {
    vi.useFakeTimers();
    useComposerDraftStore.getState().setValue("c1", "重启后还在");
    useComposerDraftStore.getState().setAttachments("c1", [attachment]);
    vi.advanceTimersByTime(400);

    expect(persisted().c1?.value).toBe("重启后还在");
    expect(persisted().c1).not.toHaveProperty("attachments");

    useComposerDraftStore.setState({
      drafts: {},
      fillToken: 0,
      dockFlipToken: 0,
    });
    __reloadComposerDraftsForTests();
    const restored = useComposerDraftStore.getState().drafts.c1;
    expect(restored?.value).toBe("重启后还在");
    expect(restored?.attachments).toEqual([]);
  });

  it("clears the persisted entry once the draft is sent (emptied)", () => {
    vi.useFakeTimers();
    useComposerDraftStore.getState().setValue("c1", "要发送的");
    vi.advanceTimersByTime(400);
    expect(persisted().c1?.value).toBe("要发送的");

    useComposerDraftStore.getState().setValue("c1", "");
    vi.advanceTimersByTime(400);
    expect(uiGet(STORAGE_LEAF)).toBeUndefined();
  });

  it("caps persistence to the most recently edited drafts", () => {
    vi.useFakeTimers();
    const s = useComposerDraftStore.getState();
    for (let i = 0; i < 35; i++) {
      vi.setSystemTime(1000 + i);
      s.setValue(`c${i}`, `草稿 ${i}`);
    }
    vi.advanceTimersByTime(400);

    const saved = persisted();
    expect(Object.keys(saved)).toHaveLength(30);
    expect(saved.c34?.value).toBe("草稿 34");
    expect(saved.c4).toBeUndefined(); // oldest five dropped
  });

  it("ignores a corrupt persisted payload", () => {
    // Bypass uiSet (which JSON.stringifies) to plant invalid JSON under the
    // same namespaced key the store reads.
    localStorage.setItem(`agentcore:${STORAGE_LEAF}`, "{not json");
    __reloadComposerDraftsForTests();
    expect(useComposerDraftStore.getState().drafts).toEqual({});
  });
});
