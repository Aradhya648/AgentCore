// Drive the share service through the REAL `api` helper by stubbing global fetch
// (mirrors workspaceOps.test.ts) so the endpoint/method/credentials contract is
// exercised, not a mocked-away api module.
import { BASE_URL } from "@/services/api";
import {
  type Share,
  createShare,
  listShares,
  revokeShare,
  shareLink,
} from "@/services/sharing";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const share = (over: Partial<Share> = {}): Share => ({
  id: "s1",
  url: "/shared/s1",
  title: "T",
  created_at: "2026-01-01T00:00:00Z",
  ...over,
});

const okJson = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("shareLink", () => {
  it("prepends the API origin to a relative /shared path (host-agnostic backend)", () => {
    expect(shareLink(share({ url: "/shared/abc" }))).toBe(
      `${BASE_URL}/shared/abc`,
    );
  });

  it("passes an already-absolute url through unchanged", () => {
    const abs = "https://share.example.com/shared/abc";
    expect(shareLink(share({ url: abs }))).toBe(abs);
  });
});

describe("share CRUD (分享对话)", () => {
  it("createShare POSTs to the conversation's shares endpoint and returns the link", async () => {
    const made = share({ id: "new" });
    fetchMock.mockResolvedValue(okJson(made));

    const res = await createShare("c1");

    expect(res).toEqual(made);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/v1/conversations/c1/shares`,
    );
    const init = fetchMock.mock.calls[0][1] as RequestInit;
    expect(init.method).toBe("POST");
    expect(init.credentials).toBe("include");
  });

  it("listShares unwraps the paginated data array", async () => {
    const data = [share({ id: "a" }), share({ id: "b" })];
    fetchMock.mockResolvedValue(okJson({ data, total: 2 }));

    const res = await listShares("c1");

    expect(res).toEqual(data);
    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/v1/conversations/c1/shares`,
    );
  });

  it("revokeShare DELETEs the specific share by id", async () => {
    fetchMock.mockResolvedValue(okJson({ status: "ok" }));

    await revokeShare("c1", "s9");

    expect(fetchMock.mock.calls[0][0]).toBe(
      `${BASE_URL}/v1/conversations/c1/shares/s9`,
    );
    expect((fetchMock.mock.calls[0][1] as RequestInit).method).toBe("DELETE");
  });
});
