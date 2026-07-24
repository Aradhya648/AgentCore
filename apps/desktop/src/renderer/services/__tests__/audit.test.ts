import { ApiError } from "@/services/api";
import { fetchFileAudit, fetchTurnAudit } from "@/services/audit";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/services/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/services/api")>();
  return {
    ...actual,
    api: {
      get: vi.fn(),
    },
  };
});

const { api } = await import("@/services/api");

describe("fetchFileAudit", () => {
  it("returns null on 404", async () => {
    vi.mocked(api.get).mockRejectedValueOnce(new ApiError(404, "{}"));
    await expect(fetchFileAudit("conv-1", "src/a.ts")).resolves.toBeNull();
  });

  it("rethrows non-404 errors", async () => {
    const err = new ApiError(500, "{}");
    vi.mocked(api.get).mockRejectedValueOnce(err);
    await expect(fetchFileAudit("conv-1", "src/a.ts")).rejects.toBe(err);
  });

  it("encodes path in query string", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: [], total: 0 });
    await fetchFileAudit("conv-1", "a b/文件.ts");
    expect(api.get).toHaveBeenCalledWith(
      "/v1/conversations/conv-1/audit/file?path=a%20b%2F%E6%96%87%E4%BB%B6.ts",
    );
  });
});

describe("fetchTurnAudit", () => {
  it("hits the turn-scoped audit endpoint", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: [], total: 0 });
    await fetchTurnAudit("conv-1", "msg-1");
    expect(api.get).toHaveBeenCalledWith(
      "/v1/conversations/conv-1/messages/msg-1/audit",
    );
  });

  it("requests causal graph when includeCausal is true", async () => {
    vi.mocked(api.get).mockResolvedValueOnce({ data: [], total: 0 });
    await fetchTurnAudit("conv-1", "msg-1", { includeCausal: true });
    expect(api.get).toHaveBeenCalledWith(
      "/v1/conversations/conv-1/messages/msg-1/audit?include_causal=true",
    );
  });
});
