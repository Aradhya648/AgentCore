import { mkdir, mkdtemp, realpath, rm, symlink } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  BrowserWindow: { getAllWindows: () => [] },
  app: { on: vi.fn() },
  ipcMain: { handle: vi.fn() },
}));

import type { StoredRoot } from "../fs/roots";
import {
  PROCESS_BUFFER_CAP,
  appendRingBuffer,
  resolveProcessCwd,
  tailLines,
} from "../process-service";

describe("appendRingBuffer", () => {
  it("concatenates under cap", () => {
    expect(appendRingBuffer("ab", "cd", 10)).toBe("abcd");
  });

  it("drops head when over cap", () => {
    const out = appendRingBuffer("AAAA", "BBBB", 6);
    expect(out).toBe("AABBBB");
    expect(out.length).toBe(6);
  });

  it("keeps only the tail at 1MB-scale", () => {
    const head = "x".repeat(100);
    const chunk = "y".repeat(PROCESS_BUFFER_CAP);
    const out = appendRingBuffer(head, chunk);
    expect(out.length).toBe(PROCESS_BUFFER_CAP);
    expect(out.endsWith("y".repeat(10))).toBe(true);
    expect(out.includes("x")).toBe(false);
  });
});

describe("tailLines", () => {
  it("returns full text when n is unset", () => {
    expect(tailLines("a\nb\nc")).toBe("a\nb\nc");
  });

  it("returns last n lines", () => {
    expect(tailLines("a\nb\nc\nd", 2)).toBe("c\nd");
  });
});

describe("resolveProcessCwd", () => {
  let dir: string;
  let root: StoredRoot;

  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "proc-cwd-")));
    root = { id: "r1", name: "ws", absPath: dir };
    await mkdir(join(dir, "apps"), { recursive: true });
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("defaults to root", async () => {
    const r = await resolveProcessCwd(root, undefined);
    expect(r).toEqual({ ok: true, cwd: dir });
  });

  it("resolves relative cwd under root", async () => {
    const r = await resolveProcessCwd(root, "apps");
    expect(r.ok).toBe(true);
    if (r.ok) {
      expect(r.cwd.replace(/\\/g, "/")).toMatch(/\/apps$/);
    }
  });

  it("rejects cwd outside root (lexical)", async () => {
    const r = await resolveProcessCwd(root, "../outside");
    expect(r.ok).toBe(false);
  });

  it("rejects cwd that escapes through a symlink ancestor", async () => {
    const outside = await realpath(await mkdtemp(join(tmpdir(), "proc-out-")));
    let linked = true;
    try {
      await symlink(outside, join(dir, "link"), "junction");
    } catch {
      linked = false;
    }
    if (linked) {
      const r = await resolveProcessCwd(root, "link");
      expect(r.ok).toBe(false);
      if (!r.ok) expect(r.detail).toContain("越出");
    }
    await rm(outside, { recursive: true, force: true });
  });
});
