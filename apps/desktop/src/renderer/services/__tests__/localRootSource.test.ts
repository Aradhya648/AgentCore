import type { FsApi, FsErrorCode, FsResult } from "@shared/ipc-contract";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  LocalFsError,
  createLocalRootSource,
} from "../sources/localRootSource";

function fail(code: FsErrorCode, reason: string): FsResult<never> {
  return { ok: false, code, reason };
}

describe("createLocalRootSource lazy workspace", () => {
  let listDir: ReturnType<typeof vi.fn>;
  let listFiles: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    listDir = vi.fn();
    listFiles = vi.fn();
    (globalThis as unknown as { window: { fsApi: Partial<FsApi> } }).window = {
      fsApi: {
        listDir: listDir as FsApi["listDir"],
        listFiles: listFiles as FsApi["listFiles"],
        readFile: vi.fn(),
        watch: vi.fn(),
        unwatch: vi.fn(),
        onChanged: () => () => {},
      },
    };
  });

  it("subpath source: base not_found → listDir returns []", async () => {
    listDir.mockResolvedValue(fail("not_found", "文件或目录不存在"));
    const src = createLocalRootSource("r1", "chat", "我的对话");
    await expect(src.listDir("")).resolves.toEqual([]);
    expect(listDir).toHaveBeenCalledWith("r1", "我的对话");
  });

  it("subpath source: base not_found → listFileIndex returns []", async () => {
    listDir.mockResolvedValue(fail("not_found", "文件或目录不存在"));
    const src = createLocalRootSource("r1", "chat", "我的对话");
    expect(src.listFileIndex).toBeDefined();
    const listFileIndex = src.listFileIndex;
    if (listFileIndex == null) throw new Error("expected listFileIndex");
    await expect(listFileIndex()).resolves.toEqual([]);
    expect(listFiles).not.toHaveBeenCalled();
  });

  it("empty subpath: root not_found → listDir throws LocalFsError", async () => {
    listDir.mockResolvedValue(fail("not_found", "文件或目录不存在"));
    const src = createLocalRootSource("r1", "project", "");
    await expect(src.listDir("")).rejects.toBeInstanceOf(LocalFsError);
    await expect(src.listDir("")).rejects.toMatchObject({
      code: "not_found",
    });
  });

  it("subpath source: out_of_root still throws (not treated as empty)", async () => {
    listDir.mockResolvedValue(fail("out_of_root", "路径越界，已拒绝"));
    const src = createLocalRootSource("r1", "chat", "ws");
    await expect(src.listDir("")).rejects.toMatchObject({
      code: "out_of_root",
    });
  });
});
