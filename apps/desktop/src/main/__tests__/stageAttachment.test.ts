/**
 * 引用即驻留：主进程占位检测 + 二进制驻留 + 暂存/finalize（纯逻辑，不碰真实 OneDrive）。
 */
import { mkdir, mkdtemp, readFile, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { execFileMock, cloudAttrs, userDataPath } = vi.hoisted(() => {
  // Must attach promisify.custom BEFORE stageAttachment module loads
  // (it does `promisify(execFile)` at import time).
  const cloudAttrs = { stdout: "Archive" };
  const custom = Symbol.for("nodejs.util.promisify.custom");
  const execFileMock = Object.assign(vi.fn(), {
    [custom]: () => Promise.resolve({ stdout: cloudAttrs.stdout, stderr: "" }),
  });
  // Placeholder until beforeEach assigns a per-test userData dir.
  const userDataPath = { current: "" };
  return { execFileMock, cloudAttrs, userDataPath };
});

vi.mock("electron", () => ({
  app: { getPath: () => userDataPath.current },
  dialog: { showOpenDialog: vi.fn() },
  BrowserWindow: { getFocusedWindow: () => null, getAllWindows: () => [] },
}));

vi.mock("node:child_process", async (importOriginal) => {
  const actual = await importOriginal<typeof import("node:child_process")>();
  return {
    ...actual,
    execFile: execFileMock,
  };
});

import { type StoredRoot, setRoot } from "../fs/roots";
import {
  ATTACH_MAX_BYTES,
  __resetStagingMemoryForTests,
  consumeStagedBytes,
  finalizeStagedAttachment,
  isCloudPlaceholder,
  stageFromAbsPath,
} from "../fs/stageAttachment";

describe("stageAttachment", () => {
  let dir: string;
  let userData: string;
  let root: StoredRoot;
  const originalPlatform = process.platform;

  beforeEach(async () => {
    dir = await mkdtemp(join(tmpdir(), "stage-att-"));
    userData = await mkdtemp(join(tmpdir(), "stage-userdata-"));
    userDataPath.current = userData;
    root = { id: "stage-root", name: "stage", absPath: dir };
    setRoot(root);
    cloudAttrs.stdout = "Archive";
    execFileMock.mockClear();
    __resetStagingMemoryForTests();
    // Hermetic default: skip PowerShell path unless a test opts into win32.
    Object.defineProperty(process, "platform", { value: "linux" });
  });

  afterEach(async () => {
    Object.defineProperty(process, "platform", { value: originalPlatform });
    await rm(dir, { recursive: true, force: true });
    await rm(userData, { recursive: true, force: true });
    __resetStagingMemoryForTests();
  });

  it("copies a text file into attachments/ and returns workspacePath", async () => {
    const src = join(dir, "notes.md");
    await writeFile(src, "# hello\n", "utf-8");
    const destDir = await mkdtemp(join(tmpdir(), "stage-dest-"));
    const destRoot: StoredRoot = {
      id: "dest-root",
      name: "dest",
      absPath: destDir,
    };
    setRoot(destRoot);
    try {
      const res = await stageFromAbsPath(src, { rootId: "dest-root" });
      expect(res.ok).toBe(true);
      if (!res.ok) return;
      expect(res.data.workspacePath).toBe("attachments/notes.md");
      expect(res.data.binary).toBe(false);
      expect(res.data.text).toContain("hello");
      const onDisk = await readFile(
        join(destDir, "attachments", "notes.md"),
        "utf-8",
      );
      expect(onDisk).toContain("hello");
    } finally {
      await rm(destDir, { recursive: true, force: true });
    }
  });

  it("stages binary xlsx-like bytes without text preview", async () => {
    const src = join(dir, "report.xlsx");
    const bytes = Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x00]);
    await writeFile(src, bytes);
    const destDir = await mkdtemp(join(tmpdir(), "stage-bin-"));
    setRoot({ id: "bin-root", name: "bin", absPath: destDir });
    try {
      const res = await stageFromAbsPath(src, { rootId: "bin-root" });
      expect(res.ok).toBe(true);
      if (!res.ok) return;
      expect(res.data.binary).toBe(true);
      expect(res.data.text).toBe("");
      expect(res.data.workspacePath).toBe("attachments/report.xlsx");
      const onDisk = await readFile(
        join(destDir, "attachments", "report.xlsx"),
      );
      expect(Buffer.compare(onDisk, bytes)).toBe(0);
    } finally {
      await rm(destDir, { recursive: true, force: true });
    }
  });

  it("dedups attachment names when dest already has the file", async () => {
    const src = join(dir, "notes.md");
    await writeFile(src, "second\n", "utf-8");
    const destDir = await mkdtemp(join(tmpdir(), "stage-dedup-"));
    await mkdir(join(destDir, "attachments"), { recursive: true });
    await writeFile(join(destDir, "attachments", "notes.md"), "first\n");
    setRoot({ id: "dedup-root", name: "dedup", absPath: destDir });
    try {
      const res = await stageFromAbsPath(src, { rootId: "dedup-root" });
      expect(res.ok).toBe(true);
      if (!res.ok) return;
      expect(res.data.workspacePath).toBe("attachments/notes (2).md");
    } finally {
      await rm(destDir, { recursive: true, force: true });
    }
  });

  it("rejects image attachments", async () => {
    const src = join(dir, "photo.png");
    await writeFile(src, Buffer.from([0x89, 0x50, 0x4e, 0x47]));
    const res = await stageFromAbsPath(src);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.reason).toContain("图片");
  });

  it("rejects oversized files", async () => {
    const src = join(dir, "huge.bin");
    expect(ATTACH_MAX_BYTES).toBe(25 * 1024 * 1024);
    await writeFile(src, "ok");
    const res = await stageFromAbsPath(src);
    expect(res.ok).toBe(true);
  });

  it("without dest returns stagingId (draft / cloud pending)", async () => {
    const src = join(dir, "pending.txt");
    await writeFile(src, "staged body\n", "utf-8");
    const res = await stageFromAbsPath(src);
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    expect(res.data.stagingId).toBeTruthy();
    expect(res.data.workspacePath).toBeUndefined();
    expect(res.data.text).toContain("staged");
  });

  it("finalizeStagedAttachment writes into local attachments/", async () => {
    const src = join(dir, "draft.bin");
    const bytes = Buffer.from([0x00, 0x01, 0x02, 0x03]);
    await writeFile(src, bytes);
    const staged = await stageFromAbsPath(src);
    expect(staged.ok).toBe(true);
    if (!staged.ok) return;
    const stagingId = staged.data.stagingId;
    expect(stagingId).toBeTruthy();
    if (!stagingId) return;

    const destDir = await mkdtemp(join(tmpdir(), "stage-fin-"));
    setRoot({ id: "fin-root", name: "fin", absPath: destDir });
    try {
      const fin = await finalizeStagedAttachment(stagingId, {
        rootId: "fin-root",
      });
      expect(fin.ok).toBe(true);
      if (!fin.ok) return;
      expect(fin.data.workspacePath).toBe("attachments/draft.bin");
      expect(fin.data.binary).toBe(true);
      const onDisk = await readFile(join(destDir, "attachments", "draft.bin"));
      expect(Buffer.compare(onDisk, bytes)).toBe(0);
    } finally {
      await rm(destDir, { recursive: true, force: true });
    }
  });

  it("consumeStagedBytes returns raw bytes for cloud PUT", async () => {
    const src = join(dir, "cloud.xlsx");
    // Include NUL so sniffBinary treats it as binary (xlsx zip header alone is not enough).
    const bytes = Buffer.from([0x50, 0x4b, 0x03, 0x04, 0x00]);
    await writeFile(src, bytes);
    const staged = await stageFromAbsPath(src);
    expect(staged.ok).toBe(true);
    if (!staged.ok) return;
    const stagingId = staged.data.stagingId;
    expect(stagingId).toBeTruthy();
    if (!stagingId) return;

    const consumed = await consumeStagedBytes(stagingId);
    expect(consumed.ok).toBe(true);
    if (!consumed.ok) return;
    expect(consumed.data.name).toBe("cloud.xlsx");
    expect(consumed.data.binary).toBe(true);
    expect(Buffer.from(consumed.data.data)).toEqual(bytes);

    // Second consume fails — staging cleared.
    const again = await consumeStagedBytes(stagingId);
    expect(again.ok).toBe(false);
  });

  it("finalize survives in-memory Map loss by rescanning attach-staging", async () => {
    const src = join(dir, "restart.txt");
    await writeFile(src, "still here\n", "utf-8");
    const staged = await stageFromAbsPath(src);
    expect(staged.ok).toBe(true);
    if (!staged.ok) return;
    const stagingId = staged.data.stagingId;
    expect(stagingId).toBeTruthy();
    if (!stagingId) return;

    // Simulate app restart: Map wiped, disk files remain under userData/attach-staging.
    __resetStagingMemoryForTests();

    const destDir = await mkdtemp(join(tmpdir(), "stage-rehydrate-"));
    setRoot({ id: "rehydrate-root", name: "rehydrate", absPath: destDir });
    try {
      const fin = await finalizeStagedAttachment(stagingId, {
        rootId: "rehydrate-root",
      });
      expect(fin.ok).toBe(true);
      if (!fin.ok) return;
      expect(fin.data.workspacePath).toBe("attachments/restart.txt");
      const onDisk = await readFile(
        join(destDir, "attachments", "restart.txt"),
        "utf-8",
      );
      expect(onDisk).toContain("still here");
    } finally {
      await rm(destDir, { recursive: true, force: true });
    }
  });

  it("consume after Map wipe fails honestly when staging dir is gone", async () => {
    const src = join(dir, "gone.txt");
    await writeFile(src, "bye\n", "utf-8");
    const staged = await stageFromAbsPath(src);
    expect(staged.ok).toBe(true);
    if (!staged.ok) return;
    const stagingId = staged.data.stagingId;
    if (!stagingId) return;

    // Wipe memory AND delete the on-disk staging folder (true loss).
    await rm(join(userData, "attach-staging", stagingId), {
      recursive: true,
      force: true,
    });
    __resetStagingMemoryForTests();

    const consumed = await consumeStagedBytes(stagingId);
    expect(consumed.ok).toBe(false);
    if (consumed.ok) return;
    expect(consumed.reason).toContain("附件暂存已失效");
  });

  it("isCloudPlaceholder returns false on non-Windows", async () => {
    const src = join(dir, "local.txt");
    await writeFile(src, "x");
    Object.defineProperty(process, "platform", { value: "linux" });
    const flagged = await isCloudPlaceholder(src);
    expect(flagged).toBe(false);
    expect(execFileMock).not.toHaveBeenCalled();
  });

  it("isCloudPlaceholder (mocked win32) flags Offline attributes", async () => {
    const src = join(dir, "cloud-placeholder.txt");
    await writeFile(src, "x");
    Object.defineProperty(process, "platform", { value: "win32" });
    cloudAttrs.stdout = "Archive, Offline, ReparsePoint";
    const flagged = await isCloudPlaceholder(src);
    expect(flagged).toBe(true);
  });

  it("stageFromAbsPath rejects when placeholder detection returns true", async () => {
    const src = join(dir, "onedrive-stub.docx");
    await writeFile(src, "x");
    Object.defineProperty(process, "platform", { value: "win32" });
    cloudAttrs.stdout = "Offline, RecallOnDataAccess";
    const res = await stageFromAbsPath(src);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.reason).toContain("未同步");
    expect(res.code).toBe("busy");
  });
});
