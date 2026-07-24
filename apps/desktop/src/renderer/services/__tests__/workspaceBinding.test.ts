import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Drive the binding calls through the REAL api client by stubbing global fetch
// (mirrors workspaceOps.test.ts), so URL/method/body and the snake→camel field
// mapping are all asserted against the actual request the server will see.
import { BASE_URL } from "@/services/api";
import {
  type WorkspaceBinding,
  bindLocalWorkspace,
  getWorkspaceBinding,
  isBoundRootMissing,
  unbindWorkspace,
} from "@/services/workspaceBinding";
import type { FsRoot } from "@shared/ipc-contract";

const URL = `${BASE_URL}/v1/conversations/c1/workspace/binding`;

const jsonResponse = (body: unknown) =>
  new Response(JSON.stringify(body), {
    status: 200,
    headers: { "Content-Type": "application/json" },
  });

const callInit = (m: ReturnType<typeof vi.fn>, call = 0): RequestInit =>
  m.mock.calls[call][1] as RequestInit;

let fetchMock: ReturnType<typeof vi.fn>;
beforeEach(() => {
  fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
});
afterEach(() => vi.unstubAllGlobals());

describe("workspace binding service", () => {
  it("reads the binding and maps root_id → rootId", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ mode: "local", scope: "folder", root_id: "root-9" }),
    );

    const b = await getWorkspaceBinding("c1");

    expect(fetchMock.mock.calls[0][0]).toBe(URL);
    expect(callInit(fetchMock).method ?? "GET").toBe("GET");
    expect(b).toEqual({
      mode: "local",
      scope: "folder",
      rootId: "root-9",
      source: null,
    });
  });

  it("binds a local root with a PUT carrying { root_id }", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ mode: "local", scope: "conversation", root_id: "root-1" }),
    );

    const b = await bindLocalWorkspace("c1", "root-1");

    expect(fetchMock.mock.calls[0][0]).toBe(URL);
    expect(callInit(fetchMock).method).toBe("PUT");
    expect(JSON.parse(callInit(fetchMock).body as string)).toEqual({
      root_id: "root-1",
    });
    expect(b).toEqual({
      mode: "local",
      scope: "conversation",
      rootId: "root-1",
      source: null,
    });
  });

  it("unbinds with a DELETE and reports the resulting cloud binding", async () => {
    fetchMock.mockResolvedValue(
      jsonResponse({ mode: "cloud", scope: "conversation", root_id: null }),
    );

    const b = await unbindWorkspace("c1");

    expect(fetchMock.mock.calls[0][0]).toBe(URL);
    expect(callInit(fetchMock).method).toBe("DELETE");
    expect(b).toEqual({
      mode: "cloud",
      scope: "conversation",
      rootId: null,
      source: null,
    });
  });
});

describe("isBoundRootMissing (§八 degradation gate)", () => {
  const roots: FsRoot[] = [
    { id: "root-1", name: "proj" },
    { id: "root-2", name: "other" },
  ];
  const local = (rootId: string | null): WorkspaceBinding => ({
    mode: "local",
    scope: "conversation",
    rootId,
    source: "explicit",
  });

  it("is false for no binding or cloud mode (nothing to lose)", () => {
    expect(isBoundRootMissing(null, roots)).toBe(false);
    expect(
      isBoundRootMissing(
        {
          mode: "cloud",
          scope: "conversation",
          rootId: null,
          source: null,
        },
        roots,
      ),
    ).toBe(false);
  });

  it("is false while the bound root is still present on this device", () => {
    expect(isBoundRootMissing(local("root-1"), roots)).toBe(false);
  });

  it("is true when the bound root is gone (removed or bound elsewhere)", () => {
    expect(isBoundRootMissing(local("root-x"), roots)).toBe(true);
    expect(isBoundRootMissing(local("root-1"), [])).toBe(true);
  });
});
