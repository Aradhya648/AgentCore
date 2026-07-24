// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { shouldUseNativeNotification } from "../nativeNotification";

describe("shouldUseNativeNotification", () => {
  const originalHidden = Object.getOwnPropertyDescriptor(document, "hidden");
  const originalHasFocus = document.hasFocus;

  beforeEach(() => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => false,
    });
    document.hasFocus = () => true;
  });

  afterEach(() => {
    if (originalHidden) {
      Object.defineProperty(document, "hidden", originalHidden);
    }
    document.hasFocus = originalHasFocus;
  });

  it("returns false when window is focused and visible", () => {
    expect(shouldUseNativeNotification()).toBe(false);
  });

  it("returns true when document is hidden", () => {
    Object.defineProperty(document, "hidden", {
      configurable: true,
      get: () => true,
    });
    expect(shouldUseNativeNotification()).toBe(true);
  });

  it("returns true when document is visible but not focused", () => {
    document.hasFocus = () => false;
    expect(shouldUseNativeNotification()).toBe(true);
  });
});
