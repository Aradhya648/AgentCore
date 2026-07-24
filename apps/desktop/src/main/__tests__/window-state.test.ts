import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { afterAll, beforeEach, describe, expect, it, vi } from "vitest";

// Throwaway userData dir the mocked `app.getPath` points at; window-state.json
// lives directly under it. Hoisted so the electron mock factory can close over it.
const h = vi.hoisted(() => {
  const base = process.env.TEMP || process.env.TMPDIR || "/tmp";
  return {
    dir: `${base}/window-state-test-${Math.random().toString(36).slice(2)}`,
    // A single 1920×1080 display at the origin; off-origin coords fall off-screen.
    workArea: { x: 0, y: 0, width: 1920, height: 1080 },
  };
});

vi.mock("electron", () => ({
  app: { getPath: () => h.dir },
  screen: { getAllDisplays: () => [{ workArea: h.workArea }] },
}));

import { loadWindowState } from "../window-state";

const stateFile = join(h.dir, "window-state.json");

function writeState(record: Record<string, unknown>): void {
  mkdirSync(h.dir, { recursive: true });
  writeFileSync(stateFile, JSON.stringify(record), "utf-8");
}

describe("loadWindowState", () => {
  beforeEach(() => {
    rmSync(h.dir, { recursive: true, force: true });
    mkdirSync(h.dir, { recursive: true });
  });
  afterAll(() => rmSync(h.dir, { recursive: true, force: true }));

  it("returns centered defaults when no file exists", () => {
    const state = loadWindowState();
    expect(state).toEqual({ width: 1400, height: 900, isMaximized: false });
    expect(state.x).toBeUndefined();
    expect(state.y).toBeUndefined();
  });

  it("restores a saved on-screen state verbatim", () => {
    writeState({ width: 1000, height: 700, x: 100, y: 80, isMaximized: true });
    expect(loadWindowState()).toEqual({
      width: 1000,
      height: 700,
      x: 100,
      y: 80,
      isMaximized: true,
    });
  });

  it("drops x/y when the saved rect is off every display", () => {
    // Saved on a now-disconnected monitor at (5000,5000) → keep size, re-center.
    writeState({ width: 1000, height: 700, x: 5000, y: 5000 });
    const state = loadWindowState();
    expect(state).toEqual({ width: 1000, height: 700, isMaximized: false });
    expect(state.x).toBeUndefined();
    expect(state.y).toBeUndefined();
  });

  it("falls back to defaults on corrupt JSON", () => {
    mkdirSync(h.dir, { recursive: true });
    writeFileSync(stateFile, "}{ not json", "utf-8");
    expect(loadWindowState()).toEqual({
      width: 1400,
      height: 900,
      isMaximized: false,
    });
  });

  it("uses default size but keeps a valid corner when only x/y were saved", () => {
    writeState({ x: 200, y: 150 });
    expect(loadWindowState()).toEqual({
      width: 1400,
      height: 900,
      x: 200,
      y: 150,
      isMaximized: false,
    });
  });
});
