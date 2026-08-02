// @vitest-environment jsdom
import {
  __clearMemoryUiStorageForTests,
  __setUiStorageBackendForTests,
  uiGet,
  UI_STORAGE_PREFIX,
} from "@/lib/uiStorage";
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import {
  loadRememberedUsername,
  REMEMBERED_USERNAME_KEY,
  saveRememberedUsername,
} from "../rememberedUsername";

const mem = new Map<string, string>();

beforeEach(() => {
  mem.clear();
  __setUiStorageBackendForTests({
    getItem: (k) => mem.get(k) ?? null,
    setItem: (k, v) => {
      mem.set(k, v);
    },
    removeItem: (k) => {
      mem.delete(k);
    },
    keys: () => [...mem.keys()],
  });
});

afterEach(() => {
  __setUiStorageBackendForTests(null);
  __clearMemoryUiStorageForTests();
});

describe("rememberedUsername", () => {
  it("returns empty when nothing stored", () => {
    expect(loadRememberedUsername()).toBe("");
  });

  it("round-trips a trimmed username under the namespaced key", () => {
    saveRememberedUsername("  alice  ");
    expect(loadRememberedUsername()).toBe("alice");
    expect(uiGet<string>(REMEMBERED_USERNAME_KEY)).toBe("alice");
    expect(mem.has(`${UI_STORAGE_PREFIX}${REMEMBERED_USERNAME_KEY}`)).toBe(
      true,
    );
  });

  it("clears storage when saving an empty username", () => {
    saveRememberedUsername("alice");
    saveRememberedUsername("  ");
    expect(loadRememberedUsername()).toBe("");
    expect(mem.has(`${UI_STORAGE_PREFIX}${REMEMBERED_USERNAME_KEY}`)).toBe(
      false,
    );
  });

  it("ignores non-string stored values", () => {
    mem.set(
      `${UI_STORAGE_PREFIX}${REMEMBERED_USERNAME_KEY}`,
      JSON.stringify({ user: "alice" }),
    );
    expect(loadRememberedUsername()).toBe("");
  });

  it("never writes a password-shaped companion key", () => {
    saveRememberedUsername("alice");
    const keys = [...mem.keys()];
    expect(keys).toEqual([`${UI_STORAGE_PREFIX}${REMEMBERED_USERNAME_KEY}`]);
    expect(keys.some((k) => /password/i.test(k))).toBe(false);
  });
});
