// @vitest-environment jsdom
/**
 * 引用即驻留：ensureAttachmentResident 本地 finalize / 云端 PUT 分支（纯 mock，不碰磁盘）。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/services/workspaceBinding", () => ({
  getWorkspaceBinding: vi.fn(),
}));
vi.mock("@/services/sidecarRouting", () => ({
  resolveConversationLocalTarget: vi.fn(),
}));
vi.mock("@/services/workspace", () => ({
  uploadWorkspaceFile: vi.fn(),
}));

import { resolveConversationLocalTarget } from "@/services/sidecarRouting";
import { uploadWorkspaceFile } from "@/services/workspace";
import { getWorkspaceBinding } from "@/services/workspaceBinding";
import {
  ATTACH_MAX_BYTES,
  ensureAttachmentResident,
  prepareBrowserFileAttachment,
  safeBrowserFileName,
} from "../resideAttachment";

const getBinding = vi.mocked(getWorkspaceBinding);
const resolveTarget = vi.mocked(resolveConversationLocalTarget);
const upload = vi.mocked(uploadWorkspaceFile);

describe("ensureAttachmentResident", () => {
  beforeEach(() => {
    getBinding.mockReset();
    resolveTarget.mockReset();
    upload.mockReset();
    // jsdom: restore a clean fsApi each test
    (window as unknown as { fsApi?: unknown }).fsApi = undefined;
  });

  it("skips when workspacePath already set", async () => {
    const res = await ensureAttachmentResident("c1", {
      name: "a.xlsx",
      workspacePath: "attachments/a.xlsx",
      binary: true,
      text: "",
      truncated: false,
    });
    expect(res).toEqual({
      ok: true,
      workspacePath: "attachments/a.xlsx",
      name: "a.xlsx",
      binary: true,
      text: "",
      truncated: false,
    });
    expect(resolveTarget).not.toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
  });

  it("legacy text-only attachment (no stagingId) returns empty workspacePath", async () => {
    const res = await ensureAttachmentResident("c1", {
      name: "讨论",
      text: "用户: hi",
      truncated: false,
    });
    expect(res).toEqual({
      ok: true,
      workspacePath: "",
      name: "讨论",
      binary: false,
      text: "用户: hi",
      truncated: false,
    });
  });

  it("binary without bytes fails instead of legacy empty path", async () => {
    const res = await ensureAttachmentResident("c1", {
      name: "a.bin",
      binary: true,
      text: "",
      truncated: false,
    });
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.reason).toContain("失效");
  });

  it("local branch finalizes staged attachment into workspace", async () => {
    getBinding.mockResolvedValue({
      mode: "local",
      scope: "conversation",
      rootId: "root-1",
      source: "explicit",
    });
    resolveTarget.mockResolvedValue({ rootId: "root-1", subpath: "scratch" });
    const finalize = vi.fn().mockResolvedValue({
      ok: true,
      data: {
        name: "notes.md",
        workspacePath: "attachments/notes.md",
        binary: false,
        text: "# hi",
        truncated: false,
        sizeBytes: 4,
      },
    });
    (window as unknown as { fsApi: Record<string, unknown> }).fsApi = {
      finalizeStagedAttachment: finalize,
    };

    const res = await ensureAttachmentResident("c1", {
      name: "notes.md",
      stagingId: "stg-1",
      text: "# hi",
      truncated: false,
    });

    expect(res).toEqual({
      ok: true,
      workspacePath: "attachments/notes.md",
      name: "notes.md",
      binary: false,
      text: "# hi",
      truncated: false,
    });
    expect(finalize).toHaveBeenCalledWith("stg-1", {
      rootId: "root-1",
      subpath: "scratch",
    });
    expect(upload).not.toHaveBeenCalled();
  });

  it("local mode without usable root refuses cloud PUT", async () => {
    getBinding.mockResolvedValue({
      mode: "local",
      scope: "conversation",
      rootId: "root-1",
      source: "explicit",
    });
    // dest null → resolveAttachDest returns null (no finalize path)
    resolveTarget.mockResolvedValue(null);
    const consume = vi.fn();
    (window as unknown as { fsApi: Record<string, unknown> }).fsApi = {
      consumeStagedBytes: consume,
    };

    const res = await ensureAttachmentResident("c1", {
      name: "x.bin",
      stagingId: "stg-2",
      text: "",
      truncated: false,
      binary: true,
    });

    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.reason).toContain("本地工作区");
    expect(consume).not.toHaveBeenCalled();
    expect(upload).not.toHaveBeenCalled();
  });

  it("cloud branch consumes staged bytes and PUTs attachments/", async () => {
    getBinding.mockResolvedValue({
      mode: "cloud",
      scope: "conversation",
      rootId: null,
      source: "container",
    });
    resolveTarget.mockResolvedValue(null);
    const bytes = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);
    const consume = vi.fn().mockResolvedValue({
      ok: true,
      data: { name: "report.xlsx", data: bytes, binary: true },
    });
    (window as unknown as { fsApi: Record<string, unknown> }).fsApi = {
      consumeStagedBytes: consume,
    };
    upload.mockResolvedValue(undefined as never);

    const res = await ensureAttachmentResident("c1", {
      name: "report.xlsx",
      stagingId: "stg-3",
      text: "",
      truncated: false,
      binary: true,
    });

    expect(res).toEqual({
      ok: true,
      workspacePath: "attachments/report.xlsx",
      name: "report.xlsx",
      binary: true,
      text: "",
      truncated: false,
    });
    expect(consume).toHaveBeenCalledWith("stg-3");
    expect(upload).toHaveBeenCalledWith(
      "c1",
      "attachments/report.xlsx",
      expect.any(Blob),
    );
  });

  it("cloud upload failure surfaces reason", async () => {
    getBinding.mockResolvedValue({
      mode: "cloud",
      scope: "conversation",
      rootId: null,
      source: "container",
    });
    resolveTarget.mockResolvedValue(null);
    (window as unknown as { fsApi: Record<string, unknown> }).fsApi = {
      consumeStagedBytes: vi.fn().mockResolvedValue({
        ok: true,
        data: {
          name: "a.bin",
          data: new Uint8Array([1]),
          binary: true,
        },
      }),
    };
    upload.mockRejectedValue(new Error("409 conflict"));

    const res = await ensureAttachmentResident("c1", {
      name: "a.bin",
      stagingId: "stg-4",
      text: "",
      truncated: false,
      binary: true,
    });
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.reason).toContain("409");
  });

  it("web fileBlob draft PUTs to attachments/ on ensure", async () => {
    getBinding.mockResolvedValue({
      mode: "cloud",
      scope: "conversation",
      rootId: null,
      source: "container",
    });
    upload.mockResolvedValue(undefined as never);
    const blob = new File([new Uint8Array([0x50, 0x4b])], "pack.docx", {
      type: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    });

    const res = await ensureAttachmentResident("c1", {
      name: "pack.docx",
      text: "",
      truncated: false,
      binary: true,
      fileBlob: blob,
    });

    expect(res).toEqual({
      ok: true,
      workspacePath: "attachments/pack.docx",
      name: "pack.docx",
      binary: true,
      text: "",
      truncated: false,
    });
    expect(upload).toHaveBeenCalledWith(
      "c1",
      "attachments/pack.docx",
      blob,
    );
  });
});

describe("prepareBrowserFileAttachment", () => {
  beforeEach(() => {
    getBinding.mockReset();
    upload.mockReset();
  });

  it("rejects images", async () => {
    const file = new File(["x"], "pic.png", { type: "image/png" });
    const res = await prepareBrowserFileAttachment(null, file);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.reason).toContain("暂不支持图片");
  });

  it("rejects oversize files", async () => {
    const file = new File(["x"], "big.bin");
    Object.defineProperty(file, "size", { value: ATTACH_MAX_BYTES + 1 });
    const res = await prepareBrowserFileAttachment(null, file);
    expect(res.ok).toBe(false);
    if (res.ok) return;
    expect(res.reason).toContain("25MB");
  });

  it("draft without conversationId holds fileBlob (binary allowed)", async () => {
    const bytes = new Uint8Array([0x00, 0x01, 0x02]);
    const file = new File([bytes], "data.bin", {
      type: "application/octet-stream",
    });
    const res = await prepareBrowserFileAttachment(null, file);
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    expect(res.binary).toBe(true);
    expect(res.fileBlob).toBe(file);
    expect(res.workspacePath).toBeUndefined();
    expect(upload).not.toHaveBeenCalled();
  });

  it("with conversationId immediately PUTs text file", async () => {
    getBinding.mockResolvedValue({
      mode: "cloud",
      scope: "conversation",
      rootId: null,
      source: "container",
    });
    upload.mockResolvedValue(undefined as never);
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    const res = await prepareBrowserFileAttachment("c9", file);
    expect(res.ok).toBe(true);
    if (!res.ok) return;
    expect(res.workspacePath).toBe("attachments/notes.txt");
    expect(res.fileBlob).toBeUndefined();
    expect(res.text).toBe("hello");
    expect(upload).toHaveBeenCalledWith("c9", "attachments/notes.txt", file);
  });

  it("safeBrowserFileName strips path and leading dots", () => {
    expect(safeBrowserFileName("..\\foo/bar.txt")).toBe("bar.txt");
    expect(safeBrowserFileName("...")).toBe("attachment");
  });
});
