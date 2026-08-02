import {
  REMEMBERED_USERNAME_KEY,
  clearRememberedUsername,
  getRememberedUsername,
  setRememberedUsername,
} from "@/lib/rememberedUsername";
// @vitest-environment jsdom
import { afterEach, describe, expect, it } from "vitest";

afterEach(() => {
  localStorage.removeItem(REMEMBERED_USERNAME_KEY);
});

describe("rememberedUsername", () => {
  it("returns null when unset", () => {
    expect(getRememberedUsername()).toBeNull();
  });

  it("persists trimmed username only", () => {
    setRememberedUsername("  alice  ");
    expect(localStorage.getItem(REMEMBERED_USERNAME_KEY)).toBe("alice");
    expect(getRememberedUsername()).toBe("alice");
  });

  it("ignores empty save", () => {
    setRememberedUsername("   ");
    expect(getRememberedUsername()).toBeNull();
  });

  it("stores only the username key (no password)", () => {
    setRememberedUsername("bob");
    expect(localStorage.getItem(REMEMBERED_USERNAME_KEY)).toBe("bob");
    // Scan storage: only our prefs key, value is the username string.
    for (let i = 0; i < localStorage.length; i++) {
      const key = localStorage.key(i);
      expect(key).toBe(REMEMBERED_USERNAME_KEY);
      if (key == null) continue;
      expect(localStorage.getItem(key)).not.toMatch(/password/i);
    }
  });

  it("clear removes the key", () => {
    setRememberedUsername("carol");
    clearRememberedUsername();
    expect(getRememberedUsername()).toBeNull();
  });
});
