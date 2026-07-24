// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * Per-conversation composer drafts (统一输入框草稿): keyed storage + 回填 + the
 * localStorage persistence layer (text survives a restart, attachments stay
 * session-only, cap keeps the map bounded). The store module is a singleton that
 * loads persisted drafts at import, so each test re-imports it fresh.
 */

const KEY = "agentcore:composer-drafts";

async function freshStore() {
  vi.resetModules();
  const [{ useComposerDraftStore, draftKeyFor }, { useConversationStore }] =
    await Promise.all([
      import("@/stores/composer"),
      import("@/stores/conversation"),
    ]);
  return { useComposerDraftStore, draftKeyFor, useConversationStore };
}

function persisted(): Record<string, { value: string; updatedAt: number }> {
  const raw = localStorage.getItem(KEY);
  return raw ? JSON.parse(raw) : {};
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
  vi.useFakeTimers();
  localStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});

describe("composer draft store", () => {
  it("keys drafts by conversation and drops emptied entries", async () => {
    const { useComposerDraftStore } = await freshStore();
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

  it("fill appends into the ACTIVE conversation's draft and bumps the focus token", async () => {
    const { useComposerDraftStore, useConversationStore, draftKeyFor } =
      await freshStore();
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

  it("persists draft TEXT (debounced) and restores it on a fresh import; attachments stay session-only", async () => {
    const first = await freshStore();
    first.useComposerDraftStore.getState().setValue("c1", "重启后还在");
    first.useComposerDraftStore.getState().setAttachments("c1", [attachment]);
    vi.advanceTimersByTime(400);

    expect(persisted().c1?.value).toBe("重启后还在");
    expect(persisted().c1).not.toHaveProperty("attachments");

    const second = await freshStore();
    const restored = second.useComposerDraftStore.getState().drafts.c1;
    expect(restored?.value).toBe("重启后还在");
    expect(restored?.attachments).toEqual([]);
  });

  it("clears the persisted entry once the draft is sent (emptied)", async () => {
    const { useComposerDraftStore } = await freshStore();
    useComposerDraftStore.getState().setValue("c1", "要发送的");
    vi.advanceTimersByTime(400);
    expect(persisted().c1?.value).toBe("要发送的");

    useComposerDraftStore.getState().setValue("c1", "");
    vi.advanceTimersByTime(400);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("caps persistence to the most recently edited drafts", async () => {
    const { useComposerDraftStore } = await freshStore();
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

  it("ignores a corrupt persisted payload", async () => {
    localStorage.setItem(KEY, "{not json");
    const { useComposerDraftStore } = await freshStore();
    expect(useComposerDraftStore.getState().drafts).toEqual({});
  });
});
