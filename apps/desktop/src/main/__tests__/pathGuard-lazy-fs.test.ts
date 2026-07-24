import { mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: { getPath: () => tmpdir() },
  dialog: {},
  ipcMain: { handle: vi.fn() },
  BrowserWindow: { getFocusedWindow: () => null, getAllWindows: () => [] },
}));

import { locate, realInside, resolveLexical } from "../fs/pathGuard";
import { type StoredRoot, setRoot } from "../fs/roots";
import { create, listDir } from "../fs/tree";

describe("pathGuard realInside / locate error codes", () => {
  let dir: string;
  let root: StoredRoot;

  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "pg-")));
    root = { id: "pg-root", name: "pg", absPath: dir };
    setRoot(root);
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("realInside returns not_found for missing path", async () => {
    const abs = join(dir, "no-such-dir");
    const r = await realInside(root, abs);
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.code).toBe("not_found");
    expect(r.reason).toContain("不存在");
  });

  it("realInside returns path for existing entry", async () => {
    await writeFile(join(dir, "f.txt"), "x");
    const r = await realInside(root, join(dir, "f.txt"));
    expect(r.ok).toBe(true);
    if (!r.ok) return;
    expect(r.path).toBe(await realpath(join(dir, "f.txt")));
  });

  it("locate marks lexical escape as out_of_root", () => {
    const r = locate(root.id, "../outside");
    expect("error" in r).toBe(true);
    if (!("error" in r)) return;
    expect(r.error).toEqual({
      ok: false,
      code: "out_of_root",
      reason: "路径越界，已拒绝",
    });
  });

  it("locate marks unknown root as unauthorized", () => {
    const r = locate("missing-root", "");
    expect("error" in r).toBe(true);
    if (!("error" in r)) return;
    if (r.error.ok) return;
    expect(r.error.code).toBe("unauthorized");
  });

  it("resolveLexical keeps in-root paths", () => {
    expect(resolveLexical(root, "a/b")).toBe(join(dir, "a", "b"));
  });
});

describe("listDir / create lazy workspace semantics", () => {
  let dir: string;
  let root: StoredRoot;

  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "fs-lazy-")));
    root = { id: "lazy-root", name: "lazy", absPath: dir };
    setRoot(root);
  });

  afterEach(async () => {
    await rm(dir, { recursive: true, force: true });
  });

  it("listDir returns not_found when subpath is missing", async () => {
    const r = await listDir(root.id, "conv-title");
    expect(r.ok).toBe(false);
    if (r.ok) return;
    expect(r.code).toBe("not_found");
  });

  it("create materializes missing parents then writes the file", async () => {
    const r = await create(root.id, "conv-title/notes.md", "file");
    expect(r.ok).toBe(true);
    const listed = await listDir(root.id, "conv-title");
    expect(listed.ok).toBe(true);
    if (!listed.ok) return;
    expect(listed.data.map((e) => e.name)).toContain("notes.md");
  });

  it("create materializes a missing directory workspace", async () => {
    const r = await create(root.id, "fresh-ws/sub", "dir");
    expect(r.ok).toBe(true);
    const listed = await listDir(root.id, "fresh-ws");
    expect(listed.ok).toBe(true);
    if (!listed.ok) return;
    expect(listed.data.some((e) => e.name === "sub" && e.kind === "dir")).toBe(
      true,
    );
  });
});
