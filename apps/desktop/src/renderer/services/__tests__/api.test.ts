import { afterEach, describe, expect, it, vi } from "vitest";
import { setSessionRenewedHandler, tryRefresh } from "../api";

afterEach(() => {
  vi.unstubAllGlobals();
  setSessionRenewedHandler(null);
});

describe("tryRefresh single-flight + three-state", () => {
  afterEach(() => {
    // Ensure Electron outboxApi path does not short-circuit cookie refresh tests.
    if (typeof globalThis !== "undefined" && "window" in globalThis) {
      Reflect.deleteProperty(
        (globalThis as { window?: object }).window as object,
        "outboxApi",
      );
    }
  });

  it("collapses concurrent refreshes into one /refresh round-trip", async () => {
    // A pending fetch that we resolve only after all three callers have raced in,
    // so the dedup (not fetch timing) is what keeps it to a single request.
    let release!: (r: Response) => void;
    const pending = new Promise<Response>((r) => {
      release = r;
    });
    const fetchMock = vi.fn((_url?: unknown) => pending);
    vi.stubGlobal("fetch", fetchMock);

    const all = Promise.all([tryRefresh(), tryRefresh(), tryRefresh()]);
    release(new Response(null, { status: 200 }));

    expect(await all).toEqual(["renewed", "renewed", "renewed"]);
    expect(fetchMock).toHaveBeenCalledTimes(1);
    expect(String(fetchMock.mock.calls[0][0])).toContain("/v1/auth/refresh");
  });

  it("starts a fresh refresh once the in-flight one has settled", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(null, { status: 200 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    expect(await tryRefresh()).toBe("renewed");
    expect(await tryRefresh()).toBe("renewed");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("returns auth_dead on 401 and resets so a later attempt can retry", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(null, { status: 401 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    expect(await tryRefresh()).toBe("auth_dead");
    // Not stuck on the previous (failed) promise — a new round-trip is issued.
    expect(await tryRefresh()).toBe("auth_dead");
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });

  it("returns transient on transport errors (non-throwing)", async () => {
    const fetchMock = vi.fn(() =>
      Promise.reject(new TypeError("Failed to fetch")),
    );
    vi.stubGlobal("fetch", fetchMock);

    await expect(tryRefresh()).resolves.toBe("transient");
  });

  it("returns transient on 5xx", async () => {
    const fetchMock = vi.fn(() =>
      Promise.resolve(new Response(null, { status: 503 })),
    );
    vi.stubGlobal("fetch", fetchMock);

    expect(await tryRefresh()).toBe("transient");
  });

  it("fires onSessionRenewed when outboxApi authRefresh renews", async () => {
    const renewed = vi.fn();
    setSessionRenewedHandler(renewed);
    const authRefresh = vi.fn(async () => "renewed" as const);
    vi.stubGlobal("window", { outboxApi: { authRefresh } });

    expect(await tryRefresh()).toBe("renewed");
    expect(authRefresh).toHaveBeenCalledOnce();
    expect(renewed).toHaveBeenCalledOnce();
  });

  it("does not fire onSessionRenewed on outboxApi transient", async () => {
    const renewed = vi.fn();
    setSessionRenewedHandler(renewed);
    const authRefresh = vi.fn(async () => "transient" as const);
    vi.stubGlobal("window", { outboxApi: { authRefresh } });

    expect(await tryRefresh()).toBe("transient");
    expect(renewed).not.toHaveBeenCalled();
  });
});
