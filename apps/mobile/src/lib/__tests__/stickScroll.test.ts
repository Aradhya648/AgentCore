import {
  STICK_ATTACH_PX,
  STICK_DETACH_PX,
  isScrollUpTouch,
  isScrollUpWheel,
  nextStickState,
} from "@/lib/stickScroll";
import { describe, expect, it } from "vitest";

describe("nextStickState", () => {
  it("stays stuck inside the detach band", () => {
    expect(nextStickState(true, STICK_DETACH_PX - 1)).toBe(true);
    expect(nextStickState(true, 0)).toBe(true);
  });

  it("detaches once past the detach band", () => {
    expect(nextStickState(true, STICK_DETACH_PX)).toBe(false);
    expect(nextStickState(true, STICK_DETACH_PX + 40)).toBe(false);
  });

  it("does not re-attach in the hysteresis gap", () => {
    expect(nextStickState(false, STICK_ATTACH_PX)).toBe(false);
    expect(nextStickState(false, 50)).toBe(false);
  });

  it("re-attaches only inside the attach band", () => {
    expect(nextStickState(false, STICK_ATTACH_PX - 1)).toBe(true);
    expect(nextStickState(false, 0)).toBe(true);
  });
});

describe("gesture direction helpers", () => {
  it("treats negative wheel delta as scroll-up", () => {
    expect(isScrollUpWheel(-12)).toBe(true);
    expect(isScrollUpWheel(12)).toBe(false);
    expect(isScrollUpWheel(0)).toBe(false);
  });

  it("treats finger moving down as scroll-up on the transcript", () => {
    expect(isScrollUpTouch(100, 120)).toBe(true);
    expect(isScrollUpTouch(120, 100)).toBe(false);
    expect(isScrollUpTouch(100, 100)).toBe(false);
  });
});
