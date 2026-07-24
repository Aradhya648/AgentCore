// `exportConversation` streams the file via the neutral raw-bytes helpers in
// `services/workspaceHttp` (authedFetch + saveBlob); mock that pair so we can
// assert the request URL and, crucially, the Content-Disposition filename parsing
// (导出对话) without touching the DOM (jsdom lacks URL.createObjectURL).
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const { authedFetchMock, saveBlobMock } = vi.hoisted(() => ({
  authedFetchMock: vi.fn(),
  saveBlobMock: vi.fn(),
}));
vi.mock("@/services/workspaceHttp", () => ({
  authedFetch: authedFetchMock,
  saveBlob: saveBlobMock,
}));

import { BASE_URL } from "@/services/api";
import { exportConversation } from "@/services/conversations";

const resWith = (disposition: string | null) => ({
  blob: async () => new Blob(["transcript"]),
  headers: new Headers(
    disposition ? { "Content-Disposition": disposition } : {},
  ),
});

beforeEach(() => {
  authedFetchMock.mockReset();
  saveBlobMock.mockReset();
});
afterEach(() => vi.restoreAllMocks());

describe("exportConversation (导出对话)", () => {
  it("requests the export endpoint with the chosen format", async () => {
    authedFetchMock.mockResolvedValue(resWith('attachment; filename="x.json"'));

    await exportConversation("c1", "json");

    expect(authedFetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/v1/conversations/c1/export?format=json`,
    );
  });

  it("defaults to markdown when no format is given", async () => {
    authedFetchMock.mockResolvedValue(resWith('attachment; filename="x.md"'));

    await exportConversation("c1");

    expect(authedFetchMock.mock.calls[0][0]).toContain("format=md");
  });

  it("prefers the RFC 5987 filename* (decoded UTF-8) for the saved name", async () => {
    const encoded = encodeURIComponent("中文标题.md");
    authedFetchMock.mockResolvedValue(
      resWith(
        `attachment; filename="conversation.md"; filename*=UTF-8''${encoded}`,
      ),
    );

    await exportConversation("c1", "md");

    expect(saveBlobMock).toHaveBeenCalledWith(expect.any(Blob), "中文标题.md");
  });

  it("falls back to the ASCII filename= when no filename* rides along", async () => {
    authedFetchMock.mockResolvedValue(
      resWith('attachment; filename="notes.json"'),
    );

    await exportConversation("c1", "json");

    expect(saveBlobMock).toHaveBeenCalledWith(expect.any(Blob), "notes.json");
  });

  it("falls back to a default name when the header is absent (not CORS-exposed)", async () => {
    authedFetchMock.mockResolvedValue(resWith(null));

    await exportConversation("c1", "json");

    expect(saveBlobMock).toHaveBeenCalledWith(
      expect.any(Blob),
      "conversation.json",
    );
  });
});
