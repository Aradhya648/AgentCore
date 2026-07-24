// @vitest-environment jsdom

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/lib/capabilities", () => ({
  hasLocalFiles: vi.fn(() => true),
}));

vi.mock("@/services/api", () => ({
  BASE_URL: "http://test",
  api: {
    post: vi.fn(),
  },
}));

vi.mock("@/services/workspaceHttp", () => ({
  authedFetch: vi.fn(),
  saveBlob: vi.fn(),
  encodePath: (p: string) => p,
  decodePreviewResponse: vi.fn(),
}));

import { hasLocalFiles } from "@/lib/capabilities";
import { api } from "@/services/api";
import { authedFetch } from "@/services/workspaceHttp";
import { exportWorkspaceToLocal } from "../workspace";

const apiPost = api.post as unknown as ReturnType<typeof vi.fn>;
const fetchMock = authedFetch as unknown as ReturnType<typeof vi.fn>;
const hasLocal = hasLocalFiles as unknown as ReturnType<typeof vi.fn>;

describe("exportWorkspaceToLocal", () => {
  beforeEach(() => {
    apiPost.mockReset();
    fetchMock.mockReset();
    hasLocal.mockReturnValue(true);
    window.fsApi = {
      checkoutArchive: vi.fn(),
    } as unknown as typeof window.fsApi;
  });

  it("snapshots, downloads zip, and checkouts via fsApi", async () => {
    apiPost.mockResolvedValue({
      snapshot_id: "snap-1",
      label: "导出到本地",
      created_at: "2026-07-15T00:00:00Z",
      size_bytes: 12,
    });
    const zipBytes = new Uint8Array([0x50, 0x4b, 0x03, 0x04]);
    fetchMock.mockResolvedValue({
      blob: async () => new Blob([zipBytes]),
    });
    const checkout = window.fsApi.checkoutArchive as ReturnType<typeof vi.fn>;
    checkout.mockResolvedValue({
      ok: true,
      destName: "Desktop",
      fileCount: 3,
    });

    const result = await exportWorkspaceToLocal("c1");

    expect(apiPost).toHaveBeenCalledWith("/v1/conversations/c1/snapshots", {
      label: "导出到本地",
    });
    expect(fetchMock).toHaveBeenCalledWith(
      "http://test/v1/conversations/c1/snapshots/snap-1/download",
    );
    expect(checkout).toHaveBeenCalledOnce();
    expect(typeof checkout.mock.calls[0][0]).toBe("string");
    expect(result).toEqual({
      ok: true,
      destName: "Desktop",
      fileCount: 3,
    });
  });

  it("returns unavailable when not desktop", async () => {
    hasLocal.mockReturnValue(false);
    const result = await exportWorkspaceToLocal("c1");
    expect(result).toEqual({ ok: false, reason: "unavailable" });
    expect(apiPost).not.toHaveBeenCalled();
  });

  it("propagates cancelled from checkout", async () => {
    apiPost.mockResolvedValue({
      snapshot_id: "snap-1",
      label: null,
      created_at: "2026-07-15T00:00:00Z",
      size_bytes: 1,
    });
    fetchMock.mockResolvedValue({
      blob: async () => new Blob([new Uint8Array([1])]),
    });
    (
      window.fsApi.checkoutArchive as ReturnType<typeof vi.fn>
    ).mockResolvedValue({ ok: false, reason: "cancelled" });

    const result = await exportWorkspaceToLocal("c1");
    expect(result).toEqual({ ok: false, reason: "cancelled" });
  });
});
