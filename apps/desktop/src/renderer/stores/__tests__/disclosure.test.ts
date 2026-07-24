// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

/**
 * 折叠/展开偏好持久化（AI 页交互状态持久化）：只落「偏离默认」的项（切回默认即删键 → 表恒收敛
 * 不膨胀）、跨「重启」（重新 import）存活、按对话前缀连带清理、损坏载荷回退空表。store 是在 import
 * 时读盘的单例，故每个用例重新 import 取干净态（对齐 composer.test 的 freshStore 写法）。
 */

const KEY = "agentcore:disclosure";

async function freshStore() {
  vi.resetModules();
  const [{ useDisclosureStore, clearDisclosureForConversation }] =
    await Promise.all([import("@/stores/disclosure")]);
  return { useDisclosureStore, clearDisclosureForConversation };
}

function persisted(): Record<string, boolean> {
  const raw = localStorage.getItem(KEY);
  return raw ? JSON.parse(raw) : {};
}

beforeEach(() => {
  localStorage.clear();
});

afterEach(() => {
  localStorage.clear();
});

describe("disclosure store", () => {
  it("stores only deviations from default and drops a key set back to its default", async () => {
    const { useDisclosureStore } = await freshStore();
    const s = useDisclosureStore.getState();

    // Deviating from default (default collapsed=false, user expands=true) records the key.
    s.setKey("c1::m1:tool:a", true, false);
    expect(useDisclosureStore.getState().map["c1::m1:tool:a"]).toBe(true);
    expect(persisted()["c1::m1:tool:a"]).toBe(true);

    // Setting it back to the default (false) drops the key entirely — table stays converged.
    s.setKey("c1::m1:tool:a", false, false);
    expect(useDisclosureStore.getState().map).not.toHaveProperty(
      "c1::m1:tool:a",
    );
    expect(persisted()).not.toHaveProperty("c1::m1:tool:a");
  });

  it("records a false deviation when the default is true (collapsing a default-open section sticks)", async () => {
    const { useDisclosureStore } = await freshStore();
    useDisclosureStore.getState().setKey("c1::run1:resource", false, true);
    expect(useDisclosureStore.getState().map["c1::run1:resource"]).toBe(false);
    expect(persisted()["c1::run1:resource"]).toBe(false);
  });

  it("is a no-op (no persist churn) when the value already matches the stored/default state", async () => {
    const { useDisclosureStore } = await freshStore();
    const s = useDisclosureStore.getState();
    // Value equals default and key absent → nothing written.
    s.setKey("c1::x", false, false);
    expect(localStorage.getItem(KEY)).toBeNull();
  });

  it("survives a fresh import (restart) from uiStorage", async () => {
    const first = await freshStore();
    first.useDisclosureStore.getState().setKey("c1::m1:reason:0", true, false);
    expect(persisted()["c1::m1:reason:0"]).toBe(true);

    const second = await freshStore();
    expect(second.useDisclosureStore.getState().map["c1::m1:reason:0"]).toBe(
      true,
    );
  });

  it("clears only the target conversation's keys", async () => {
    const { useDisclosureStore, clearDisclosureForConversation } =
      await freshStore();
    const s = useDisclosureStore.getState();
    s.setKey("c1::m1:tool:a", true, false);
    s.setKey("c1::m2:reason:0", true, false);
    s.setKey("c2::m9:tool:z", true, false);

    clearDisclosureForConversation("c1");

    const map = useDisclosureStore.getState().map;
    expect(map).not.toHaveProperty("c1::m1:tool:a");
    expect(map).not.toHaveProperty("c1::m2:reason:0");
    expect(map["c2::m9:tool:z"]).toBe(true); // untouched
    expect(persisted()["c2::m9:tool:z"]).toBe(true);
  });

  it("clearConversationUiState also clears disclosure via the registered clearer", async () => {
    vi.resetModules();
    const { useDisclosureStore } = await import("@/stores/disclosure");
    const { clearConversationUiState } = await import(
      "@/lib/clearConversationUiState"
    );

    useDisclosureStore.getState().setKey("c1::m1:tool:a", true, false);
    useDisclosureStore.getState().setKey("c2::m9:tool:z", true, false);

    clearConversationUiState("c1");

    const map = useDisclosureStore.getState().map;
    expect(map).not.toHaveProperty("c1::m1:tool:a");
    expect(map["c2::m9:tool:z"]).toBe(true);
  });

  it("ignores a corrupt persisted payload", async () => {
    localStorage.setItem(KEY, "{not json");
    const { useDisclosureStore } = await freshStore();
    expect(useDisclosureStore.getState().map).toEqual({});
  });
});
