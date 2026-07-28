import {
  MAX_SANE_RUNNING_ELAPSED_SEC,
  runningElapsedSec,
} from "@/lib/runningElapsed";
import { describe, expect, it } from "vitest";

describe("runningElapsedSec", () => {
  it("returns floor seconds for recent starts", () => {
    const now = 1_700_000_000_000;
    expect(runningElapsedSec(now - 45_000, now)).toBe(45);
  });

  it("clamps absurd offline-preview skew to 0 (omit Ns suffix)", () => {
    const now = 1_700_000_000_000;
    const started = now - (MAX_SANE_RUNNING_ELAPSED_SEC + 1) * 1000;
    expect(runningElapsedSec(started, now)).toBe(0);
  });

  it("returns 0 for null / NaN", () => {
    expect(runningElapsedSec(null)).toBe(0);
    expect(runningElapsedSec(Number.NaN)).toBe(0);
  });
});
