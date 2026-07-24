import { mkdir, mkdtemp, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("electron", () => ({
  app: { getPath: () => tmpdir() },
  dialog: {},
  ipcMain: { handle: vi.fn() },
  BrowserWindow: { getFocusedWindow: () => null, getAllWindows: () => [] },
  shell: { trashItem: vi.fn(), showItemInFolder: vi.fn(), openPath: vi.fn() },
  clipboard: { writeText: vi.fn() },
}));

import type { WorkspaceOpResult } from "@shared/ipc-contract";
import { shell } from "electron";
import { type StoredRoot, executeWorkspaceOp } from "../fs-service";
import { setRoot } from "../fs/roots";
import { trashPath } from "../fs/shell";
import { listDir } from "../fs/tree";

const valOf = (r: WorkspaceOpResult): unknown => {
  if (!r.ok) throw new Error(`expected ok, got ${JSON.stringify(r.error)}`);
  return r.value;
};

describe("workspace listing hide system files", () => {
  let dir: string;
  let root: StoredRoot;

  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "ws-hide-")));
    root = { id: "r-hide", name: "r", absPath: dir };
    setRoot(root);
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await rm(dir, { recursive: true, force: true });
  });

  it("index_files prunes .agentcore, *.db, and media (AI tier)", async () => {
    await writeFile(join(dir, "notes.md"), "hi");
    await writeFile(join(dir, "hero.png"), "png");
    await mkdir(join(dir, ".agentcore", "index"), { recursive: true });
    await writeFile(join(dir, ".agentcore", "index", "code_search.db"), "x");
    await writeFile(join(dir, "local.db"), "x");
    const res = valOf(await executeWorkspaceOp(root, "index_files", {})) as {
      paths: string[];
    };
    expect(res.paths).toEqual(["notes.md"]);
  });

  it("listDir hides system noise but keeps media visible for the file UI", async () => {
    await writeFile(join(dir, "notes.md"), "hi");
    await writeFile(join(dir, "hero.png"), "png");
    await mkdir(join(dir, ".agentcore"), { recursive: true });
    await writeFile(join(dir, "local.db"), "x");
    const listed = await listDir(root.id, "");
    expect(listed.ok).toBe(true);
    if (!listed.ok) return;
    expect(listed.data.map((e) => e.name).sort()).toEqual([
      "hero.png",
      "notes.md",
    ]);
  });
});

describe("trashPath soft-delete", () => {
  let dir: string;
  let root: StoredRoot;

  beforeEach(async () => {
    dir = await realpath(await mkdtemp(join(tmpdir(), "ws-trash-")));
    root = { id: "r-trash", name: "r", absPath: dir };
    setRoot(root);
    (shell.trashItem as ReturnType<typeof vi.fn>).mockReset();
    (shell.trashItem as ReturnType<typeof vi.fn>).mockResolvedValue(undefined);
  });

  afterEach(async () => {
    vi.restoreAllMocks();
    await rm(dir, { recursive: true, force: true });
  });

  it("moves a scratch subdir to the OS trash", async () => {
    const scratch = join(dir, "conversations", "c1");
    await mkdir(scratch, { recursive: true });
    await writeFile(join(scratch, "a.md"), "x");
    const res = await trashPath(root.id, "conversations/c1");
    expect(res.ok).toBe(true);
    expect(shell.trashItem).toHaveBeenCalledWith(scratch);
  });

  it("rejects trashing the root itself", async () => {
    const res = await trashPath(root.id, "");
    expect(res.ok).toBe(false);
    expect(shell.trashItem).not.toHaveBeenCalled();
  });

  it("treats a missing lazy scratch as success", async () => {
    const res = await trashPath(root.id, "conversations/missing");
    expect(res.ok).toBe(true);
    expect(shell.trashItem).not.toHaveBeenCalled();
  });
});
