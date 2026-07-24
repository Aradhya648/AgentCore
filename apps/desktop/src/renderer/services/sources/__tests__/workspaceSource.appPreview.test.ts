// @vitest-environment jsdom

import type { PreviewApi } from "@shared/preview-contract";
import { afterEach, describe, expect, it, vi } from "vitest";

// 侧邻模块只在 resolve* 分支用到，这里只测 createWorkspaceSource 门控 → 桩掉即可（避免拉 react-query）。
vi.mock("@/hooks/useConversations", () => ({
  getConversations: vi.fn(() => []),
}));
vi.mock("@/services/sidecarRouting", () => ({
  resolveConversationLocalTarget: vi.fn(),
}));

import { createWorkspaceSource } from "@/services/sources/workspaceSource";

describe("createWorkspaceSource — 应用内「完整预览」入口门控", () => {
  afterEach(() => {
    window.previewApi = undefined;
  });

  it("桌面：window.previewApi 存在 → 挂 openInAppPreview 并按契约路由到 previewApi.open", async () => {
    const open = vi.fn().mockResolvedValue({ ok: true });
    window.previewApi = { open } as unknown as PreviewApi;

    const source = createWorkspaceSource("c1", "工作区");
    expect(typeof source.openInAppPreview).toBe("function");

    await source.openInAppPreview?.("dir/index.html");
    expect(open).toHaveBeenCalledWith({
      conversationId: "c1",
      path: "dir/index.html",
    });
  });

  it("失败结果（ok:false）→ 抛出 reason 供 UI toast", async () => {
    const open = vi.fn().mockResolvedValue({ ok: false, reason: "打不开" });
    window.previewApi = { open } as unknown as PreviewApi;

    const source = createWorkspaceSource("c1");
    await expect(source.openInAppPreview?.("index.html")).rejects.toThrow(
      "打不开",
    );
  });

  it("web：无 window.previewApi → 不挂 openInAppPreview（入口不暴露）", () => {
    const source = createWorkspaceSource("c1");
    expect(source.openInAppPreview).toBeUndefined();
  });
});
